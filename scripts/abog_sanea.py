"""Sanea abogado_responsable con el extractor EN VIVO (ancla de footer + belongs-check)
sobre TODOS los casos. Detecta:
  - COORDINADORA mal puesta (María Cristina = revisora, nunca responsable).
  - DISCREPANCIA: el extractor halla un redactor del roster (belongs-OK) DISTINTO al guardado.
  - PRESTADO: guardado set pero el extractor da None y NO hay respuesta que pertenezca
    (posible atribución de doc prestado, tipo c1).
NO escribe salvo --apply (solo corrige coordinadora + prestados claros; discrepancias se
reportan para criterio humano — no se pisa curación manual a ciegas).
Uso: [--apply].
"""
import sys, os, json
os.environ["V9_OCR_SCANNED"] = "false"
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.database.database import SessionLocal
from backend.database.models import Case, Document, AuditLog
from backend.v9.field_extractor import (
    extract_abogado_responsable_for_case, _is_respuesta_doc,
    _doc_belongs_to_case, _accionante_tokens, _rad_corto_from_23,
    _rad_corto_from_folder, _footer_zone,
)

APPLY = "--apply" in sys.argv
CORD = "MARIA CRISTINA"  # coordinadora (nunca responsable)
db = SessionLocal()

def has_belonging_response(c):
    acc = _accionante_tokens(c.accionante)
    rads = {r for r in (c.radicado_23_digitos, c.radicado_forest,
            _rad_corto_from_23(c.radicado_23_digitos),
            _rad_corto_from_folder(c.folder_name)) if r}
    for d in db.query(Document).filter(Document.case_id == c.id).all():
        if not _is_respuesta_doc(d):
            continue
        t = d.extracted_text or _footer_zone(d) or ""
        if t and (not (acc or rads) or _doc_belongs_to_case(acc, rads, t, getattr(d, "filename", "") or "")):
            return True
    return False

coord = []; discrep = []; prestado = []
for c in db.query(Case).all():
    cur = (c.abogado_responsable or "").strip()
    if not cur:
        continue
    val, src = extract_abogado_responsable_for_case(db, c)
    if CORD in cur.upper():
        coord.append((c.id, cur, val))
    elif val and src in ("roster_nombre", "catalogo", "roster_correo") and val.upper() != cur.upper():
        discrep.append((c.id, cur, val))
    elif not val and not has_belonging_response(c):
        prestado.append((c.id, cur))

print(f"COORDINADORA mal puesta: {len(coord)}")
for cid, cur, v in coord: print(f"  c{cid}: {cur!r} → extractor={v!r}")
print(f"\nDISCREPANCIA (extractor roster ≠ guardado): {len(discrep)}")
for cid, cur, v in discrep: print(f"  c{cid}: guardado={cur!r} vs extractor={v!r}")
print(f"\nPRESTADO/sin-respuesta-que-pertenezca (guardado pero extractor None): {len(prestado)}")
for cid, cur in prestado[:40]: print(f"  c{cid}: {cur!r}")

json.dump({"coord": coord, "discrep": discrep, "prestado": prestado},
          open("data/abog_sanea.json", "w"), ensure_ascii=False)

if APPLY:
    n = 0
    for cid, cur, v in coord:
        c = db.query(Case).filter(Case.id == cid).first()
        c.abogado_responsable = v if (v and v.upper() != cur.upper()) else None
        db.add(AuditLog(case_id=cid, action="SANEA_ABOGADO", source="abog_sanea",
                        new_value=f"coordinadora {cur!r}→{c.abogado_responsable!r}"))
        n += 1
    db.commit()
    print(f"\nCoordinadoras corregidas: {n}. (Discrepancias y prestados NO se tocan sin tu OK.)")
else:
    print("\nDRY-RUN.")
db.close()
