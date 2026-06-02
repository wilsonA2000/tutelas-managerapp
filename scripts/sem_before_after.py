#!/usr/bin/env python3
"""Antes/después: corre las funciones REALES modificadas (extract_asunto/derecho
con use_llm=True) y compara contra el valor actual en DB (source=regex). NO escribe."""
from __future__ import annotations
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.database.database import SessionLocal
from backend.database.models import Case
from backend.v9.field_extractor import extract_asunto_for_case, extract_derecho_vulnerado_for_case

ids = [int(x) for x in sys.argv[1:]]
db = SessionLocal()
try:
    for cid in ids:
        c = db.query(Case).filter(Case.id == cid).first()
        if not c:
            print(json.dumps({"case": cid, "err": "no existe"})); continue
        a_new, a_src = extract_asunto_for_case(db, c, use_llm=True)
        d_new, d_src = extract_derecho_vulnerado_for_case(db, c, use_llm=True)
        print(json.dumps({
            "case": cid,
            "asunto": f"{c.asunto}  ->  {a_new} [{a_src}]",
            "derecho": f"{c.derecho_vulnerado}  ->  {d_new} [{d_src}]",
        }, ensure_ascii=False), flush=True)
finally:
    db.close()
