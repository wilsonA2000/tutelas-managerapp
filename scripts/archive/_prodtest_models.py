#!/usr/bin/env python3
"""Bake-off SOBRE EL PIPELINE DE PRODUCCIÓN (no harness sintético).

Invoca `backend.v9.pipeline.extract_case` (dry-run, use_llm=True) — el MISMO
pipeline que usa la app — sobre los casos de prueba, contra el modelo cargado en
:8765. Se corre una vez por modelo (Qwen3-4B / Phi-4-mini), intercambiando el
llama-server. Mide los campos semánticos reales + latencia.

Salida: data/prodtest_<modelo>.json
"""
from __future__ import annotations
import json, os, sys, time, urllib.request
from pathlib import Path
from backend.database.database import SessionLocal
from backend.v9.pipeline import extract_case

ROOT = Path(__file__).resolve().parents[1]
# Casos por argv, o el set por defecto (5 con verdad conocida).
CASES = [int(x) for x in sys.argv[1:]] or [427, 189, 307, 15, 284]
# CRUDO (determinista, sin modelo) = PRODTEST_LLM=0 ; HARNESS (con LLM) = 1 (default).
USE_LLM = os.getenv("PRODTEST_LLM", "1") == "1"
TAG = "harness" if USE_LLM else "crudo"


def model_name() -> str:
    try:
        return json.loads(urllib.request.urlopen("http://127.0.0.1:8765/v1/models", timeout=10).read())["data"][0]["id"]
    except Exception:
        return "desconocido"


def main():
    model = model_name(); safe = model.replace("/", "_").replace(".gguf", "")
    print(f"=== PROD-TEST [{TAG}] · {model} · {len(CASES)} casos ===", file=sys.stderr)
    db = SessionLocal()
    out = {"model": model, "modo": TAG, "cases": {}}
    try:
        for cid in CASES:
            t0 = time.time()
            res = extract_case(db, cid, dry_run=True, use_llm=USE_LLM)
            dt = time.time() - t0
            f = res.fields.to_dict() if hasattr(res.fields, "to_dict") else dict(res.fields.__dict__)
            rec = {"lat_s": round(dt, 1),
                   "sentido_fallo_1st": f.get("sentido_fallo_1st"),
                   "derecho_vulnerado": f.get("derecho_vulnerado"),
                   "asunto": f.get("asunto"),
                   "pretensiones": (f.get("pretensiones") or "")[:120],
                   "completitud": f.get("completitud")}
            out["cases"][cid] = rec
            print(f"  {cid}: sent={rec['sentido_fallo_1st']} der={rec['derecho_vulnerado']} asu={(rec['asunto'] or '')[:34]} compl={rec['completitud']} ({rec['lat_s']}s)", file=sys.stderr)
    finally:
        db.close()
    avg = sum(c["lat_s"] for c in out["cases"].values()) / len(out["cases"])
    out["lat_prom_s"] = round(avg, 1)
    fn = f"prodtest_{TAG}_{safe}.json"
    (ROOT / "data" / fn).write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n[{TAG}] {model}: latencia prom {out['lat_prom_s']}s/caso -> data/{fn}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
