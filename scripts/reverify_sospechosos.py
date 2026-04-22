"""v5.1 Sprint 2 — Re-verify docs SOSPECHOSO con datos v5.0 actualizados.

Tras v5.0: 100% de casos COMPLETO tienen rad23 (antes 94.2%).
Muchos docs fueron marcados SOSPECHOSO con datos incompletos del caso;
re-ejecutando verify_document_belongs con los datos nuevos, se espera que
un % significativo quede OK.

Uso:
    python3 scripts/reverify_sospechosos.py              # aplica a todos SOSPECHOSO
    python3 scripts/reverify_sospechosos.py --limit 20   # solo 20 (prueba)
    python3 scripts/reverify_sospechosos.py --dry-run    # no persiste cambios
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database.database import SessionLocal, wal_checkpoint
from backend.database.models import Document, Case, AuditLog
from backend.extraction.pipeline import verify_document_belongs

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reverify")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-revisar", action="store_true", help="Incluir verificacion=REVISAR tambien")
    args = parser.parse_args()

    db = SessionLocal()
    statuses = ["SOSPECHOSO"]
    if args.include_revisar:
        statuses.append("REVISAR")

    q = db.query(Document).filter(Document.verificacion.in_(statuses))
    if args.limit:
        q = q.limit(args.limit)
    docs = q.all()

    logger.info("Docs a re-verificar: %d (statuses: %s)", len(docs), statuses)

    transitions = {}  # (old, new) -> count
    details = []

    for i, doc in enumerate(docs, 1):
        case = db.query(Case).filter(Case.id == doc.case_id).first()
        if not case:
            continue
        old_status = doc.verificacion
        try:
            new_status, new_detail = verify_document_belongs(case, doc)
        except Exception as e:
            logger.warning("[%d/%d] error en doc %d: %s", i, len(docs), doc.id, str(e)[:80])
            continue

        transitions[(old_status, new_status)] = transitions.get((old_status, new_status), 0) + 1

        if new_status != old_status:
            details.append((doc.id, doc.filename, old_status, new_status, new_detail[:60]))
            if not args.dry_run:
                doc.verificacion = new_status
                doc.verificacion_detalle = f"Re-verify v5.1: {new_detail[:180]}"
                db.add(AuditLog(
                    case_id=doc.case_id or 0, field_name="verificacion",
                    old_value=old_status, new_value=new_status,
                    action="REVERIFY_V51", source=f"doc_id={doc.id}",
                ))

        if i % 50 == 0:
            if not args.dry_run:
                db.commit()
            logger.info("  progreso: %d/%d", i, len(docs))

    if not args.dry_run:
        db.commit()
        wal_checkpoint("PASSIVE")
    db.close()

    logger.info("═" * 60)
    logger.info("Re-verify completado%s:", " (DRY RUN)" if args.dry_run else "")
    logger.info("Transiciones:")
    for (old, new), n in sorted(transitions.items(), key=lambda x: -x[1]):
        flag = "✅" if new == "OK" else "⚠️ " if new == "SOSPECHOSO" else "❌"
        logger.info("  %s %s → %s : %d", flag, old, new, n)
    if details:
        logger.info("Primeras 10 transiciones con cambio:")
        for d in details[:10]:
            logger.info("  doc=%d old=%s new=%s %s", d[0], d[2], d[3], d[4])


if __name__ == "__main__":
    main()
