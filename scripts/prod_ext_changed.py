"""Extracción de producción (use_llm) sobre los casos que cambiaron esta sesión
(docs nuevos de la ingesta). UNO A UNO (no batch → evita GPU hang en iGPU). Sticky
protege lo curado. Captura antes/después de campos clave. Uso: [--apply]."""
import sys, json, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.database.database import SessionLocal
from backend.database.models import Case
from backend.v9.pipeline import extract_case

APPLY = "--apply" in sys.argv
IDS = json.load(open("data/changed_cases.json"))
FIELDS = ("accionante", "asunto", "derecho_vulnerado", "abogado_responsable", "juzgado",
          "sentido_fallo_1st", "sentido_fallo_2nd", "impugnacion", "incidente", "estado",
          "fecha_fallo_1st", "fecha_fallo_2nd", "parte_resolutiva_1st", "parte_resolutiva_2nd")
db = SessionLocal()
changes = {}
for i, cid in enumerate(IDS):
    c = db.query(Case).filter(Case.id == cid).first()
    if not c:
        print(f"[{i+1}/{len(IDS)}] c{cid} NO EXISTE", flush=True); continue
    before = {k: getattr(c, k, None) for k in FIELDS}
    try:
        extract_case(db, cid, dry_run=not APPLY, use_llm=True)
    except Exception as e:
        print(f"[{i+1}/{len(IDS)}] c{cid} ERROR: {e}", flush=True)
        traceback.print_exc()
        continue
    db.refresh(c)
    after = {k: getattr(c, k, None) for k in FIELDS}
    diff = {k: (before[k], after[k]) for k in FIELDS if before[k] != after[k]}
    if diff:
        changes[cid] = {k: {"antes": v[0], "despues": v[1]} for k, v in diff.items()}
    tag = " ".join(f"{k}={after[k]!r}" for k in diff) if diff else "(sin cambios - sticky)"
    print(f"[{i+1}/{len(IDS)}] c{cid} ({(c.accionante or '')[:20]}) -> {len(diff)} campos | {tag[:90]}", flush=True)
json.dump(changes, open("data/prod_ext_changed_diff.json", "w"), ensure_ascii=False, indent=1)
print(f"\nDONE {'APPLY' if APPLY else 'DRY'} - {len(changes)}/{len(IDS)} casos con cambios")
db.close()
