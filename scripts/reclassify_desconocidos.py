"""Script de backfill: reclasifica docs DESCONOCIDO/PDF_OTRO con extracted_text.

Uso:
  ./venv/bin/python3 scripts/reclassify_desconocidos.py --dry-run   # ver qué cambiaría
  ./venv/bin/python3 scripts/reclassify_desconocidos.py             # aplicar

El clasificador por contenido requiere ≥2 señales para comprometerse con un tipo;
de lo contrario mantiene el tipo original.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.database.database import SessionLocal
from backend.database.models import Document, AuditLog
from backend.extraction.doc_ops import classify_doc_type_by_content
from backend.core.time import utcnow


def main() -> int:
    ap = argparse.ArgumentParser(description="Reclasifica DESCONOCIDO/PDF_OTRO por contenido.")
    ap.add_argument("--dry-run", action="store_true", default=False,
                    help="Solo mostrar cambios, no escribir en DB")
    ap.add_argument("--limit", type=int, default=0,
                    help="Máximo de documentos a procesar (0 = todos)")
    args = ap.parse_args()

    TARGET_TYPES = {"DESCONOCIDO", "PDF_OTRO"}

    changed = 0
    kept = 0

    # Una sola sesión: consulta y escritura en la misma transacción
    with SessionLocal() as db:
        q = db.query(Document).filter(
            Document.doc_type.in_(TARGET_TYPES),
            Document.extracted_text.isnot(None),
            Document.extracted_text != "",
        )
        if args.limit:
            q = q.limit(args.limit)
        docs = q.all()

        print(f"Documentos candidatos ({'/'.join(TARGET_TYPES)}): {len(docs)}")
        if not docs:
            print("Nada que reclasificar.")
            return 0

        for doc in docs:
            new_type = classify_doc_type_by_content(
                doc.filename or "", doc.extracted_text or ""
            )
            if new_type == doc.doc_type or new_type == "PDF_OTRO":
                kept += 1
                continue

            fn = (doc.filename or "")[:40]
            print(f"  [{doc.id}] {fn!r:42s}  {doc.doc_type} -> {new_type}")
            if not args.dry_run:
                old_type = doc.doc_type
                doc.doc_type = new_type
                doc.updated_at = utcnow()
                db.add(AuditLog(
                    case_id=doc.case_id,
                    field_name="doc_type",
                    old_value=old_type,
                    new_value=new_type,
                    action="RECLASSIFY_BY_CONTENT",
                    source="script:reclassify_desconocidos",
                ))
            changed += 1

        if not args.dry_run and changed:
            db.commit()

    mode = "[DRY-RUN] " if args.dry_run else ""
    print(f"\n{mode}Reclasificados: {changed}  Sin cambio: {kept}  Total: {len(docs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
