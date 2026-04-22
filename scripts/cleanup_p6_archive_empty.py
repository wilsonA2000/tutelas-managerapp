"""P6 — Archivar casos vacíos persistentes (>60 días sin docs).

Estrategia:
- Casos sin documentos asociados.
- Antigüedad (created_at) > 60 días.
- NO eliminar: cambiar processing_status='ARCHIVADO'.
- Preservar audit trail.

Dry-run por defecto.
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from sqlalchemy import text
from backend.database.database import SessionLocal
from backend.database.models import Case, AuditLog


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--days", type=int, default=60, help="edad mínima en días")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        threshold = datetime.utcnow() - timedelta(days=args.days)

        # Casos sin documentos
        empty = db.execute(
            text("""
                SELECT c.id, c.folder_name, c.created_at, c.processing_status
                FROM cases c
                LEFT JOIN documents d ON d.case_id = c.id
                WHERE c.created_at < :t
                GROUP BY c.id
                HAVING COUNT(d.id) = 0
            """),
            {"t": threshold},
        ).fetchall()

        print(f"Casos vacíos >{args.days} días: {len(empty)}")
        print()
        for row in empty[:15]:
            print(f"  case#{row[0]} created {row[2]} status={row[3]} name={row[1]}")
        if len(empty) > 15:
            print(f"  ... y {len(empty)-15} más")

        archived = 0
        if args.apply:
            for row in empty:
                cid = row[0]
                old_status = row[3]
                if old_status == "ARCHIVADO":
                    continue
                db.execute(
                    text("UPDATE cases SET processing_status='ARCHIVADO' WHERE id=:id"),
                    {"id": cid},
                )
                db.add(AuditLog(
                    case_id=cid,
                    field_name="processing_status",
                    old_value=old_status or "",
                    new_value="ARCHIVADO",
                    action="P6_ARCHIVE_EMPTY",
                    source=f"cleanup_p6; age>{args.days}d; no_docs",
                ))
                archived += 1
            db.commit()
            print(f"\n✅ {archived} casos archivados")
        else:
            db.rollback()
            print(f"\n⚠️  DRY-RUN. {len(empty)} candidatos.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
