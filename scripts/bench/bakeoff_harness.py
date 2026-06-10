#!/usr/bin/env python3
"""Fase 1 — Arnés de PRODUCCIÓN con scoring (extiende scripts/bakeoff_harness.py).

Corre el pipeline real `extract_case(dry_run=True, use_llm=True)` sobre los 60 casos
dorados contra el modelo cargado en BENCH_PORT (8766 por defecto), y puntúa cada caso
contra el gold set con scripts/bench/scorecard.py. Captura calidad + velocidad
(warm vs cold) + procedencia + degeneración.

SEGURO: dry-run (no escribe DB). Habla con el server del bench vía LLM_LOCAL_URL,
NO con el :8765 de producción. La copia de DB la decide quien invoca (TUTELAS_DB / cwd).

Env (los setea bakeoff_matrix.sh):
    BENCH_TAG          etiqueta de la celda (model__config__cache)
    BENCH_CONFIG       string legible de la config (para el reporte)
    BENCH_SERVER_LOG   ruta al log del llama-server (para parsear tok/s)
    BENCH_SERVER_PID   pid del server (para muestrear RSS)
    LLM_LOCAL_URL      http://127.0.0.1:8766  ← apunta al server del bench
    V9_DOC_CACHE       'true'|'false' (eje caché de DB de docs)
    V9_LLM_SOFT_JSON   'true' para MoE
Salida: data/bench/<TAG>.json
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "bench"))

import scorecard as sc  # noqa: E402
from backend.database.database import SessionLocal  # noqa: E402
from backend.v9.pipeline import extract_case  # noqa: E402

GOLDEN = ROOT / "data" / "golden" / "golden_v1.json"
OUT_DIR = ROOT / "data" / "bench"
LLM_URL = os.getenv("LLM_LOCAL_URL", "http://127.0.0.1:8766")


def load_golden() -> tuple[dict, dict]:
    raw = json.loads(GOLDEN.read_text(encoding="utf-8"))
    meta = raw.pop("_meta", {})
    # claves = case_id (str) -> {field: valor|null}. null (JSON) -> None (vacío verificado).
    gold = {int(k): v for k, v in raw.items()}
    return gold, meta


def model_name() -> str:
    try:
        data = json.loads(urllib.request.urlopen(f"{LLM_URL}/v1/models", timeout=10).read())
        return data["data"][0]["id"]
    except Exception:
        return "desconocido"


def parse_tokps(log_path: str | None) -> dict:
    """Best-effort: tok/s de prompt-eval (prefill) y eval (decode) del log del server."""
    if not log_path or not Path(log_path).exists():
        return {}
    txt = Path(log_path).read_text(errors="ignore")
    pp = [float(m) for m in re.findall(r"prompt eval time.*?([\d.]+) tokens per second", txt)]
    tg = [float(m) for m in re.findall(r"\beval time.*?([\d.]+) tokens per second", txt)]
    out = {}
    if pp:
        out["prefill_tokps_avg"] = round(sum(pp) / len(pp), 1)
    if tg:
        out["decode_tokps_avg"] = round(sum(tg) / len(tg), 1)
    return out


def peak_rss_mb(pid: str | None) -> float | None:
    if not pid:
        return None
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmHWM:"):  # high-water mark
                return round(int(line.split()[1]) / 1024, 1)
    except Exception:
        return None
    return None


def main() -> int:
    gold, gmeta = load_golden()
    tag = os.getenv("BENCH_TAG") or model_name().replace("/", "_").replace(".gguf", "")
    case_ids = sorted(gold.keys())
    _maxc = os.getenv("BENCH_MAX_CASES")
    if _maxc:
        case_ids = case_ids[:int(_maxc)]
    model = model_name()
    print(f"=== BENCH [{tag}] · {model} · {len(case_ids)} dorados · {LLM_URL} ===", file=sys.stderr)
    if gmeta.get("status") == "UNVERIFIED_SEED":
        print("  ⚠ gold UNVERIFIED_SEED: alucinación/abstención aún no medibles (faltan null curados).",
              file=sys.stderr)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    out = {
        "tag": tag, "model": model,
        "config": os.getenv("BENCH_CONFIG", ""),
        "cache_doc": os.getenv("V9_DOC_CACHE", "true"),
        "soft_json": os.getenv("V9_LLM_SOFT_JSON", "false"),
        "llm_url": LLM_URL,
        "golden_status": gmeta.get("status", "unknown"),
        "cases": {},
    }
    try:
        for i, cid in enumerate(case_ids):
            t0 = time.time()
            try:
                res = extract_case(db, cid, dry_run=True, use_llm=True)
            except Exception as e:  # noqa: BLE001
                print(f"  {cid}: ERROR {e}", file=sys.stderr)
                out["cases"][str(cid)] = {"error": str(e)}
                continue
            dt = round(time.time() - t0, 2)
            pred = res.fields.values
            sources = res.fields.sources_json()
            score = sc.score_case(gold[cid], pred)
            out["cases"][str(cid)] = {
                "lat_s": dt,
                "phase": "cold" if i == 0 else "warm",   # 1er caso = KV frío
                "llm_calls": getattr(res, "llm_calls", None),
                "llm_fields": sorted(k for k, v in sources.items() if v == "llm"),
                "completitud": res.fields.completitud(),
                "counts": score["counts"],
                "degenerate": score["degenerate"],
                "accuracy_present": score["accuracy_present"],
                "hallucination_rate": score["hallucination_rate"],
            }
            c = out["cases"][str(cid)]["counts"]
            print(f"  {cid}: {dt}s [{out['cases'][str(cid)]['phase']}] "
                  f"acc={out['cases'][str(cid)]['accuracy_present']} "
                  f"match={c['match']} miss={c['missed']} halu={c['hallucinated']} deg={out['cases'][str(cid)]['degenerate']}",
                  file=sys.stderr)
    finally:
        db.close()

    # Agregados de velocidad (warm vs cold) y calidad
    ok = [c for c in out["cases"].values() if "lat_s" in c]
    warm = [c["lat_s"] for c in ok if c["phase"] == "warm"]
    cold = [c["lat_s"] for c in ok if c["phase"] == "cold"]
    accs = [c["accuracy_present"] for c in ok if c["accuracy_present"] is not None]
    halu = [c["hallucination_rate"] for c in ok if c["hallucination_rate"] is not None]
    out["agg"] = {
        "n_cases": len(ok),
        "lat_warm_avg_s": round(sum(warm) / len(warm), 2) if warm else None,
        "lat_cold_s": round(sum(cold) / len(cold), 2) if cold else None,
        "lat_total_s": round(sum(c["lat_s"] for c in ok), 1),
        "accuracy_present_avg": round(sum(accs) / len(accs), 3) if accs else None,
        "hallucination_rate_avg": round(sum(halu) / len(halu), 3) if halu else None,
        "degenerate_total": sum(c["degenerate"] for c in ok),
        "llm_calls_total": sum((c.get("llm_calls") or 0) for c in ok),
        **parse_tokps(os.getenv("BENCH_SERVER_LOG")),
        "peak_rss_mb": peak_rss_mb(os.getenv("BENCH_SERVER_PID")),
    }
    fn = OUT_DIR / f"{tag}.json"
    fn.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    a = out["agg"]
    print(f"\n[{tag}] warm {a['lat_warm_avg_s']}s · cold {a['lat_cold_s']}s · "
          f"acc {a['accuracy_present_avg']} · halu {a['hallucination_rate_avg']} · "
          f"deg {a['degenerate_total']} -> {fn}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
