"""Rellena parte_resolutiva_1st (verbatim RESUELVE, determinista) para una lista de casos
usando el extractor de produccion. Solo escribe si esta vacio. Audita.
Uso: python3 scripts/curacion_parte_resolutiva.py [--apply]
"""
import sys, os
os.environ.setdefault("V9_DISABLE_LLM", "true")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datetime import datetime, timezone
from backend.database.database import SessionLocal
from backend.database.models import Case, AuditLog
from backend.v9.field_extractor import extract_parte_resolutiva_1ra_for_case

APPLY = "--apply" in sys.argv
CASES = [109,408,413,420,437,438,439,449,451,456,457,461,465,470,472,476,478,479,490,518,529]
db = SessionLocal()
ts = datetime.now(timezone.utc).isoformat()
ok = miss = skip = 0
for cid in CASES:
    c = db.query(Case).filter(Case.id == cid).first()
    if c is None:
        continue
    if (c.parte_resolutiva_1st or "").strip():
        skip += 1; print(f"  c{cid}: YA_TIENE ({len((c.parte_resolutiva_1st or ''))} chars)"); continue
    val, src = extract_parte_resolutiva_1ra_for_case(db, c)
    if val and val.strip():
        ok += 1
        print(f"  c{cid}: [{src}] {len(val)} chars: {val[:90]!r}")
        if APPLY:
            old = c.parte_resolutiva_1st
            c.parte_resolutiva_1st = val
            c.updated_at = ts
            db.add(AuditLog(case_id=cid, field_name="parte_resolutiva_1st", old_value=old,
                            new_value=val[:300], action="CURACION_CAMPO", source=f"parte_resolutiva:{src}", timestamp=ts))
    else:
        miss += 1
        print(f"  c{cid}: SIN_RESUELVE (extractor no hallo zona; revisar truncado/disco)")
if APPLY:
    db.commit()
print(f"\n{'APLICADO' if APPLY else 'DRY-RUN'}: {ok} extraidos, {miss} sin resuelve, {skip} ya tenian")
db.close()
