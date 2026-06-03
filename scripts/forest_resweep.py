"""Barrido FOREST: corrige los radicado_forest mal-formados (prefijo rad23 '68...',
Proc#/IDs legacy que no empiezan con año) y rellena vacíos, re-extrayendo con el
extractor ya arreglado (_extract_forest year-prefixed). Uso: [--apply].

Un FOREST válido es: continuo year-prefixed (^20YY...) o nuevo (N-20YY-NNNNNN-NNNN).
Todo lo demás se considera mal-formado → se re-extrae (resultado puede ser correcto o None).
"""
import sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.database.database import SessionLocal
from backend.database.models import Case, AuditLog
from backend.v9.field_extractor import extract_forest_for_case

APPLY = "--apply" in sys.argv
_VALID_CONT = re.compile(r"^20[12]\d\d{5,9}$")        # 20YY + 5-9 díg
_VALID_NUEVO = re.compile(r"^\d-20\d\d-\d{6}-\d{4,6}$")

def is_valid(f):
    f = (f or "").strip()
    return bool(_VALID_CONT.match(f) or _VALID_NUEVO.match(f))

db = SessionLocal()
allc = db.query(Case).all()
malformados = [c for c in allc if (c.radicado_forest or "").strip() and not is_valid(c.radicado_forest)]
vacios = [c for c in allc if not (c.radicado_forest or "").strip()]
print(f"Malformados: {len(malformados)} | Vacíos: {len(vacios)}")

cambios = {"corregido": [], "nulleado": [], "rellenado": [], "sigue_vacio": []}
for c in malformados + vacios:
    nuevo, imp = extract_forest_for_case(db, c)
    old = (c.radicado_forest or "").strip()
    if nuevo and is_valid(nuevo):
        if old and old != nuevo:
            cambios["corregido"].append((c.id, old, nuevo))
        elif not old:
            cambios["rellenado"].append((c.id, nuevo))
        if APPLY:
            c.radicado_forest = nuevo
            if imp and is_valid(imp) and not (c.forest_impugnacion or ""):
                c.forest_impugnacion = imp
            db.add(AuditLog(case_id=c.id, action="FIX_FOREST", source="forest_resweep",
                            new_value=f"forest {old!r}->{nuevo}"))
    else:
        if old:  # tenía valor malo y no hay reemplazo válido → NULL
            cambios["nulleado"].append((c.id, old))
            if APPLY:
                c.radicado_forest = None
                db.add(AuditLog(case_id=c.id, action="FIX_FOREST", source="forest_resweep",
                                new_value=f"forest {old!r}->NULL (sin FOREST válido en docs)"))
        else:
            cambios["sigue_vacio"].append(c.id)
if APPLY:
    db.commit()

for k in ("corregido", "rellenado", "nulleado"):
    items = cambios[k]
    print(f"\n=== {k.upper()} ({len(items)}) ===")
    for it in items[:40]:
        print("   ", it)
print(f"\nsigue_vacio (sin FOREST en docs, honesto): {len(cambios['sigue_vacio'])}")
db.close()
print("\n" + ("APLICADO" if APPLY else "DRY-RUN"))
