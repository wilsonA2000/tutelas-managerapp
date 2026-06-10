"""Rellena parte_resolutiva_1st (verbatim RESUELVE, determinista, lee disco sin cap)
para los casos que tienen sentido_fallo_1st pero no parte. Auto-localiza el doc del
fallo de 1ra (no solo SENTENCIA_1RA: tambien FALLO/PDF_SENTENCIA mal rotulados),
excluye 2da instancia. Uso: [--apply].
"""
import sys, os
os.environ.setdefault("V9_DISABLE_LLM", "true")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datetime import datetime, timezone
from backend.database.database import SessionLocal
from backend.database.models import Case, Document, AuditLog
from backend.v9.field_extractor import _dispositiva_verbatim, _is_segunda_instancia

APPLY = "--apply" in sys.argv
db = SessionLocal()
ts = datetime.now(timezone.utc)

targets = [c for c in db.query(Case).all()
           if (c.sentido_fallo_1st or "").strip() and not (c.parte_resolutiva_1st or "").strip()]

def fallo_docs(cid):
    docs = db.query(Document).filter(Document.case_id == cid).all()
    def sc(d):
        dt = (d.doc_type or "").upper(); fn = (d.filename or "").upper(); s = 0
        if dt == "SENTENCIA_1RA": s += 10
        if "FALLO" in fn or "SENTENCIA" in fn: s += 6
        if dt == "PDF_SENTENCIA": s += 5
        if dt == "DESCONOCIDO": s += 1
        if "2DA" in fn or "SEGUNDA" in fn or "IMPUGNAC" in (dt + fn): s -= 12
        if "AUTO" in dt or "INCIDENT" in dt or "RESPUESTA" in dt or "DEMANDA" in dt: s -= 4
        return s
    return sorted([d for d in docs if sc(d) > -2], key=sc, reverse=True)

ok = miss = 0
for c in targets:
    got = None
    for d in fallo_docs(c.id)[:5]:
        if _is_segunda_instancia(d):
            continue
        v = _dispositiva_verbatim(d)
        if v and len(v) >= 40:
            got = (v, d.id); break
    if got:
        ok += 1
        print(f"  c{c.id} [{c.sentido_fallo_1st}] doc{got[1]}: {got[0][:70]!r}")
        if APPLY:
            c.parte_resolutiva_1st = got[0]; c.updated_at = ts
            db.add(AuditLog(case_id=c.id, field_name="parte_resolutiva_1st", old_value=None,
                            new_value=got[0][:300], action="CURACION_CAMPO",
                            source=f"parteres_sweep:{got[1]}", timestamp=ts))
    else:
        miss += 1
        print(f"  c{c.id} [{c.sentido_fallo_1st}]: SIN_RESUELVE (revisar)")
if APPLY:
    db.commit()
print(f"\n{'APLICADO' if APPLY else 'DRY-RUN'}: {ok} extraidos, {miss} sin resuelve (de {len(targets)})")
db.close()
