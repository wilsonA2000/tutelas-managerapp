#!/usr/bin/env python3
"""Baseline PRE-orquestador: mide extract_case REAL de producción (dry-run,
use_llm=True) sobre N casos reales. Cuenta llamadas LLM reales (intercepta
requests.post a :8765), tiempo por etapa, y campos llenados por fuente.

NO escribe a DB (dry_run=True). Estos son los números "ANTES" para comparar
contra el orquestador. Uso: venv/bin/python scripts/baseline_extraction.py --n 6
"""
import os, sys, time, argparse, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=6)
ap.add_argument("--cases", type=str, default="", help="IDs fijos coma-separados")
args = ap.parse_args()

# Contar llamadas LLM reales (:8765) por AMBAS vías: requests.post (field_extractor)
# Y urllib.request.urlopen (gap_fill usa urllib, no requests).
_llm = {"n": 0, "secs": 0.0}

import requests
_orig_post = requests.post
def _counting_post(url, *a, **k):
    is_llm = "8765" in str(url)
    t = time.time(); r = _orig_post(url, *a, **k)
    if is_llm:
        _llm["n"] += 1; _llm["secs"] += time.time() - t
    return r
requests.post = _counting_post

import urllib.request
_orig_urlopen = urllib.request.urlopen
def _counting_urlopen(req, *a, **k):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    is_llm = "8765" in str(url)
    t = time.time(); r = _orig_urlopen(req, *a, **k)
    if is_llm:
        _llm["n"] += 1; _llm["secs"] += time.time() - t
    return r
urllib.request.urlopen = _counting_urlopen

from backend.database.database import SessionLocal
from backend.v9.pipeline import extract_case
from backend.v9.types import FieldSource

db = SessionLocal()
if args.cases:
    case_ids = [int(x) for x in args.cases.split(",") if x.strip()]
else:
    # Casos reales con documentos con texto (workload representativo)
    import sqlite3
    c = sqlite3.connect(os.path.join(os.path.dirname(__file__), "..", "data", "tutelas.db"))
    rows = c.execute("""
        select d.case_id, count(*) nd from documents d
        where length(trim(coalesce(d.extracted_text,'')))>300 and d.case_id is not null
        group by d.case_id having nd>=3 order by d.case_id desc limit ?""", (args.n,)).fetchall()
    case_ids = [r[0] for r in rows]
    c.close()

print(f"BASELINE pre-orquestador · {len(case_ids)} casos · dry-run · use_llm=True")
print(f"casos: {case_ids}\n")

agg = {"total": 0.0, "llm_calls": 0, "llm_secs": 0.0, "needed_llm": 0}
rowsout = []
for cid in case_ids:
    _llm["n"] = 0; _llm["secs"] = 0.0
    t0 = time.time()
    try:
        res = extract_case(db, cid, dry_run=True, use_llm=True)
    except Exception as e:
        print(f"  case {cid}: ERROR {str(e)[:100]}"); continue
    wall = time.time() - t0
    nf = sum(1 for s in res.fields.sources.values() if s != FieldSource.EMPTY)
    nllm_fields = sum(1 for s in res.fields.sources.values() if s == FieldSource.LLM)
    fe_ms = res.timing_ms.get("field_extractor", 0)
    gap_ms = res.timing_ms.get("llm_gap_fill", 0)
    agg["total"] += wall; agg["llm_calls"] += _llm["n"]; agg["llm_secs"] += _llm["secs"]
    if _llm["n"] > 0: agg["needed_llm"] += 1
    rowsout.append((cid, wall, _llm["n"], _llm["secs"], nf, nllm_fields, fe_ms, gap_ms))
    print(f"  case {cid:4}: {wall:6.1f}s · LLM_calls={_llm['n']} ({_llm['secs']:.0f}s) · "
          f"campos={nf} (LLM={nllm_fields}) · field_extr={fe_ms/1000:.0f}s gap={gap_ms/1000:.0f}s")

n = len(rowsout)
print(f"\n=== AGREGADO ({n} casos) ===")
print(f"  tiempo total: {agg['total']:.0f}s · promedio: {agg['total']/max(n,1):.1f}s/caso")
print(f"  casos que invocaron LLM: {agg['needed_llm']}/{n}")
print(f"  llamadas LLM totales: {agg['llm_calls']} (prom {agg['llm_calls']/max(n,1):.1f}/caso)")
print(f"  tiempo en LLM: {agg['llm_secs']:.0f}s ({100*agg['llm_secs']/max(agg['total'],1):.0f}% del total)")
db.close()
