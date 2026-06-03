"""Aplica los abogado_responsable recuperados del roster (de data/abog_plan.json).
Solo escribe los que resolvieron a un canónico del roster de 17 (los externos CPS y
los 'sin Proyectó' NO se tocan, regla Wilson). Uso: [--apply]."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.database.database import SessionLocal
from backend.database.models import Case, AuditLog

APPLY = "--apply" in sys.argv
plan = json.load(open("data/abog_plan.json"))
db = SessionLocal()
n = 0
for cid, v in plan.items():
    canon = v.get("canonical")
    if not canon:
        continue
    c = db.query(Case).filter(Case.id == int(cid)).first()
    if not c:
        continue
    if (c.abogado_responsable or "").strip():
        print(f"  c{cid}: YA tiene abogado ({c.abogado_responsable}) — skip")
        continue
    print(f"  {'SET' if APPLY else 'DRY'} c{cid}: abogado_responsable = {canon} (de {v.get('src')})")
    if APPLY:
        c.abogado_responsable = canon
        db.add(AuditLog(case_id=int(cid), action="FIX_ABOGADO", source="abog_apply",
                        new_value=f"abogado_responsable={canon} (redactor Proyectó, doc {v.get('src')})"))
        n += 1
if APPLY:
    db.commit()
    print(f"\nAplicados: {n}")
else:
    print("\nDRY-RUN (usa --apply)")
db.close()
