"""Backfill retroactivo del vinculo Document.email_id para docs legacy.

Recorre la tabla `emails` y para cada email busca Documents que matcheen
por tres estrategias (en orden de confianza):

  A) file_path == attachment.saved_path (match exacto)
  B) case_id + filename == attachment.filename (para renames/typos)
  C) Para EMAIL_MD: case_id + filename contiene fecha/subject del email

Los que matchean ganan email_id + email_message_id.
Los que no matchean quedan con email_id=NULL (legacy).

Idempotente: skip docs que ya tienen email_id asignado.

Uso:
    python -m backend.database.migrations.v48_backfill_email_provenance
    python -m backend.database.migrations.v48_backfill_email_provenance --dry-run
"""

import argparse
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from backend.database.database import SessionLocal
from backend.database.models import Document, Email

logger = logging.getLogger("tutelas.migrations")


def _normalize_filename(name: str) -> str:
    """Normaliza nombre de archivo para comparar (quita \\r\\n, espacios extra)."""
    if not name:
        return ""
    return " ".join(name.replace("\r", " ").replace("\n", " ").split()).strip().lower()


def backfill_email_provenance(db: Session, dry_run: bool = False) -> dict:
    """Vincula Documents legacy al Email de origen por tres estrategias.

    Returns:
        dict con estadisticas: emails_procesados, docs_linkeados_A, _B, _C,
        docs_sin_match, duracion_s
    """
    start = datetime.utcnow()
    stats = {
        "emails_procesados": 0,
        "emails_sin_attachments": 0,
        "docs_linkeados_A_exact_path": 0,
        "docs_linkeados_B_case_filename": 0,
        "docs_linkeados_C_email_md": 0,
        "docs_ya_linkeados_skip": 0,
        "dry_run": dry_run,
    }

    # Cargar todos los emails con attachments en memoria (hay <2000)
    emails = db.query(Email).all()
    logger.info("Loaded %d emails for backfill", len(emails))

    for email in emails:
        stats["emails_procesados"] += 1
        atts = email.attachments or []

        # --- ESTRATEGIA A: match exacto por file_path ---
        if atts:
            att_paths = {a.get("saved_path") for a in atts if a.get("saved_path")}
            if att_paths:
                docs_match_A = (
                    db.query(Document)
                    .filter(
                        Document.file_path.in_(att_paths),
                        Document.email_id.is_(None),  # solo los que NO estan linkeados
                    )
                    .all()
                )
                for doc in docs_match_A:
                    if not dry_run:
                        doc.email_id = email.id
                        doc.email_message_id = email.message_id
                    stats["docs_linkeados_A_exact_path"] += 1

            # --- ESTRATEGIA B: match por case_id + filename normalizado ---
            if email.case_id:
                att_filenames_norm = {
                    _normalize_filename(a.get("filename", ""))
                    for a in atts if a.get("filename")
                }
                att_filenames_norm.discard("")

                if att_filenames_norm:
                    # Candidatos: docs del mismo caso, sin email_id, que NO hayan
                    # sido matched por A (filter por path ya hecho)
                    candidates = (
                        db.query(Document)
                        .filter(
                            Document.case_id == email.case_id,
                            Document.email_id.is_(None),
                        )
                        .all()
                    )
                    for doc in candidates:
                        doc_fn_norm = _normalize_filename(doc.filename or "")
                        if doc_fn_norm in att_filenames_norm:
                            if not dry_run:
                                doc.email_id = email.id
                                doc.email_message_id = email.message_id
                            stats["docs_linkeados_B_case_filename"] += 1
        else:
            stats["emails_sin_attachments"] += 1

        # --- ESTRATEGIA C: EMAIL_MD por case + fecha/subject del email ---
        # Los .md tienen nombre tipo Email_YYYYMMDD_Subject.md
        if email.case_id and email.date_received:
            date_str = email.date_received.strftime("%Y%m%d")
            md_candidates = (
                db.query(Document)
                .filter(
                    Document.case_id == email.case_id,
                    Document.doc_type == "EMAIL_MD",
                    Document.email_id.is_(None),
                    Document.filename.like(f"Email_{date_str}_%"),
                )
                .all()
            )
            for doc in md_candidates:
                # Validacion extra: que el subject normalizado este contenido en el filename
                subj_key = _normalize_filename((email.subject or "")[:50]).replace(" ", "_")
                if not subj_key or subj_key[:20] in _normalize_filename(doc.filename).replace(" ", "_"):
                    if not dry_run:
                        doc.email_id = email.id
                        doc.email_message_id = email.message_id
                    stats["docs_linkeados_C_email_md"] += 1

        # Commit cada 50 emails para no hacer una transaccion gigante
        if not dry_run and stats["emails_procesados"] % 50 == 0:
            db.commit()
            logger.info("Commit batch: %d emails procesados", stats["emails_procesados"])

    if not dry_run:
        db.commit()

    # Contar docs sin match (post-backfill)
    stats["docs_total"] = db.query(Document).count()
    stats["docs_con_email_id"] = db.query(Document).filter(Document.email_id.isnot(None)).count()
    stats["docs_sin_email_id"] = stats["docs_total"] - stats["docs_con_email_id"]
    stats["cobertura_pct"] = round(stats["docs_con_email_id"] / stats["docs_total"] * 100, 2) if stats["docs_total"] else 0
    stats["duracion_s"] = round((datetime.utcnow() - start).total_seconds(), 1)

    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Backfill v4.8 email provenance")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin escribir")
    args = parser.parse_args()

    import json
    with SessionLocal() as db:
        result = backfill_email_provenance(db, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))
