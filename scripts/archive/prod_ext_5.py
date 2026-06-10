import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.database.database import SessionLocal
from backend.database.models import Case
from backend.v9.pipeline import extract_case
IDS = [181, 453, 92, 475, 387]
APPLY = "--apply" in sys.argv
db = SessionLocal()
for cid in IDS:
    c = db.query(Case).filter(Case.id == cid).first()
    before = {k: getattr(c, k) for k in ("asunto","derecho_vulnerado","abogado_responsable","juzgado","sentido_fallo_1st","sentido_fallo_2nd","impugnacion","incidente","estado")}
    print(f"\n=== c{cid} ({(c.accionante or '')[:24]}) ===", flush=True)
    try:
        res = extract_case(db, cid, dry_run=not APPLY, use_llm=True)
    except Exception as e:
        print(f"  ERROR: {e}"); continue
    db.refresh(c)
    after = {k: getattr(c, k) for k in before}
    for k in before:
        if APPLY and before[k] != after[k]:
            print(f"  {k}: {before[k]!r} -> {after[k]!r}")
    if not APPLY:
        # mostrar lo que el pipeline propone (de res si lo expone)
        print(f"  (dry-run) docs reclasificados/extraídos — ver result")
db.close()
print("\nDONE", "APPLY" if APPLY else "DRY")
