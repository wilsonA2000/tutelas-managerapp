"""Rellena parte_resolutiva_1st apuntando al doc_id EXACTO del fallo (los agentes los
hallaron; muchos estan mal rotulados PDF_SENTENCIA/DEMANDA_TUTELA). Usa el helper de
produccion _dispositiva_verbatim (lee ultimas 5 pag del PDF de disco, sin cap 30k).
Solo escribe si esta vacio. Audita. Uso: [--apply].
"""
import sys, os
os.environ.setdefault("V9_DISABLE_LLM", "true")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datetime import datetime, timezone
from backend.database.database import SessionLocal
from backend.database.models import Case, Document, AuditLog
from backend.v9.field_extractor import _dispositiva_verbatim

APPLY = "--apply" in sys.argv
# case_id -> doc_id del fallo (de los hallazgos de los agentes)
MAP = {
    413: 6017, 420: 6042, 437: 6129, 438: 6124, 439: 6253, 449: 5764, 451: 6001,
    456: 6015, 457: 6112, 461: 6108, 465: 6287, 470: 6153, 472: 6259, 476: 6171,
    479: 6213, 490: 6168, 529: 6341,
}
db = SessionLocal()
ts = datetime.now(timezone.utc)
ok = miss = skip = 0
for cid, did in MAP.items():
    c = db.query(Case).filter(Case.id == cid).first()
    if c is None:
        continue
    if (c.parte_resolutiva_1st or "").strip():
        skip += 1; print(f"  c{cid}: YA_TIENE"); continue
    d = db.query(Document).filter(Document.id == did).first()
    if d is None:
        miss += 1; print(f"  c{cid}: doc{did} NO_EXISTE"); continue
    val = _dispositiva_verbatim(d)
    if val and val.strip() and len(val) >= 40:
        ok += 1
        print(f"  c{cid} (doc{did}): {len(val)} chars: {val[:80]!r}")
        if APPLY:
            c.parte_resolutiva_1st = val
            c.updated_at = ts
            db.add(AuditLog(case_id=cid, field_name="parte_resolutiva_1st", old_value=None,
                            new_value=val[:300], action="CURACION_CAMPO",
                            source=f"parte_resolutiva_doc:{did}", timestamp=ts))
    else:
        miss += 1
        print(f"  c{cid} (doc{did}): SIN_RESUELVE (val={val!r:.60})")
if APPLY:
    db.commit()
print(f"\n{'APLICADO' if APPLY else 'DRY-RUN'}: {ok} extraidos, {miss} sin resuelve, {skip} ya tenian")
db.close()
