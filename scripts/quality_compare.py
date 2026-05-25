#!/usr/bin/env python3
"""Compara la salida ACTUAL del pipeline contra el baseline de calidad guardado
(data/quality_baseline_preorquestador.json). Re-corre extract_case real (dry-run,
use_llm=True) sobre los MISMOS casos del baseline y diffea campo-por-campo.

Úsalo tras CADA cambio del orquestador: si algún campo cambió → revisar/revertir.
Uso: venv/bin/python scripts/quality_compare.py
"""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASELINE = os.path.join(os.path.dirname(__file__), "..", "data", "quality_baseline_preorquestador.json")
with open(BASELINE, encoding="utf-8") as fh:
    base = json.load(fh)

from backend.database.database import SessionLocal
from backend.v9.pipeline import extract_case

db = SessionLocal()
SEM = ("asunto", "categoria_tematica", "derecho_vulnerado", "pretensiones",
       "accionados", "vinculados", "quien_impugno", "decision_incidente",
       "responsable_desacato")

changed = 0
same = 0
for cid, rec in base.items():
    res = extract_case(db, int(cid), dry_run=True, use_llm=True)
    print(f"--- case {cid} ---")
    for f in SEM:
        old = (rec[f]["value"] or "").strip()
        new = (res.fields.values.get(f, "") or "").strip()
        if old == new:
            same += 1
        else:
            changed += 1
            print(f"  ⚠️  {f}:")
            print(f"      ANTES: {old[:110]!r}")
            print(f"      AHORA: {new[:110]!r}")
db.close()
print(f"\n{'='*60}")
if changed == 0:
    print(f"✅ CALIDAD INTACTA — 0 campos cambiaron ({same} idénticos)")
else:
    print(f"⚠️  {changed} campos CAMBIARON ({same} idénticos) — revisar si mejora o degrada")
