#!/usr/bin/env python3
"""Baseline de CALIDAD pre-orquestador: captura los VALORES que el pipeline
actual (extract_case real, dry-run, use_llm=True) produce para los campos
semánticos LLM-fillable en N casos. Es la red de regresión: cualquier cambio
futuro (orquestador) se compara contra este JSON campo-por-campo.

NO escribe a DB. Guarda a data/quality_baseline_preorquestador.json (gitignored: PII).
Uso: venv/bin/python scripts/quality_baseline.py --cases <id1,id2,...>
"""
import os, sys, json, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ap = argparse.ArgumentParser()
ap.add_argument("--cases", type=str, required=True,
                help="IDs de caso coma-separados (sin default: no hardcodear casos reales)")
args = ap.parse_args()
case_ids = [int(x) for x in args.cases.split(",") if x.strip()]

from backend.database.database import SessionLocal
from backend.v9.pipeline import extract_case

# Campos semánticos que el LLM puede llenar (los que el orquestador tocaría)
SEM_FIELDS = ("asunto", "categoria_tematica", "derecho_vulnerado", "pretensiones",
              "accionados", "vinculados", "quien_impugno", "decision_incidente",
              "responsable_desacato")

db = SessionLocal()
out = {}
for cid in case_ids:
    res = extract_case(db, cid, dry_run=True, use_llm=True)
    rec = {}
    for f in SEM_FIELDS:
        val = res.fields.values.get(f, "")
        src = res.fields.sources.get(f)
        rec[f] = {"value": val, "source": src.value if src else "empty"}
    out[str(cid)] = rec
    print(f"--- case {cid} ---")
    for f in SEM_FIELDS:
        v = rec[f]["value"]
        if v:
            print(f"  {f:20} [{rec[f]['source']:7}] {v[:90]}")
db.close()

dst = os.path.join(os.path.dirname(__file__), "..", "data", "quality_baseline_preorquestador.json")
with open(dst, "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=2)
print(f"\n✅ Baseline de calidad guardado: {dst}")
print("   (referencia de regresión — comparar el orquestador campo-por-campo contra esto)")
