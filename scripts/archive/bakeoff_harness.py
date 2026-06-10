#!/usr/bin/env python3
"""Bake-off harness — corre el pipeline de PRODUCCIÓN (`extract_case`, dry-run,
use_llm=True) sobre un set de casos, contra el modelo cargado en :8765.

A diferencia de `_prodtest_models.py`, captura el cuadro COMPLETO + la procedencia
por campo (regex/catalog/excel/llm) + llm_calls, para que `bakeoff_compare.py`
pueda enfocar el diff en los campos que realmente vienen del LLM (donde 4B y 30B
difieren; el resto lo resuelve el determinista idéntico).

Uso:
    BAKEOFF_TAG=4B python3 scripts/bakeoff_harness.py 400 406 412 ...
Salida: data/bakeoff_<TAG>.json
"""
from __future__ import annotations
import json, os, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # permite `import backend.*` al correr como script

from backend.database.database import SessionLocal
from backend.v9.pipeline import extract_case
# Set por defecto: 8 "vacíos" (el LLM se dispara) + 5 "llenos" con verdad conocida.
DEFAULT_CASES = [400, 406, 412, 417, 418, 419, 423, 425, 25, 45, 307, 5, 15]
CASES = [int(x) for x in sys.argv[1:]] or DEFAULT_CASES
TAG = os.getenv("BAKEOFF_TAG", "")


def model_name() -> str:
    try:
        data = json.loads(urllib.request.urlopen("http://127.0.0.1:8765/v1/models", timeout=10).read())
        return data["data"][0]["id"]
    except Exception:
        return "desconocido"


def main() -> int:
    model = model_name()
    tag = TAG or model.replace("/", "_").replace(".gguf", "")
    print(f"=== BAKE-OFF [{tag}] · {model} · {len(CASES)} casos ===", file=sys.stderr)
    db = SessionLocal()
    out = {"tag": tag, "model": model, "cases": {}}
    try:
        for cid in CASES:
            t0 = time.time()
            try:
                res = extract_case(db, cid, dry_run=True, use_llm=True)
            except Exception as e:
                print(f"  {cid}: ERROR {e}", file=sys.stderr)
                out["cases"][str(cid)] = {"error": str(e)}
                continue
            dt = round(time.time() - t0, 1)
            fields = res.fields.to_dict() if hasattr(res.fields, "to_dict") else dict(res.fields.__dict__)
            sources = res.fields.sources_json() if hasattr(res.fields, "sources_json") else {}
            llm_calls = getattr(res, "llm_calls", None)
            # Campos cuya autoridad final fue el LLM (lo discriminante entre modelos).
            llm_fields = sorted(k for k, v in sources.items() if v == "llm")
            rec = {
                "lat_s": dt,
                "llm_calls": llm_calls,
                "llm_fields": llm_fields,
                "fields": fields,
                "sources": sources,
            }
            out["cases"][str(cid)] = rec
            print(f"  {cid}: {dt}s · llm_calls={llm_calls} · campos_llm={llm_fields}", file=sys.stderr)
    finally:
        db.close()
    lats = [c["lat_s"] for c in out["cases"].values() if "lat_s" in c]
    out["lat_prom_s"] = round(sum(lats) / len(lats), 1) if lats else None
    out["lat_total_s"] = round(sum(lats), 1)
    fn = ROOT / "data" / f"bakeoff_{tag}.json"
    fn.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n[{tag}] {model}: prom {out['lat_prom_s']}s/caso · total {out['lat_total_s']}s -> {fn}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
