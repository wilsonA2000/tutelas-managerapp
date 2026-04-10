"""Cleanup actions v4.8: operaciones mutadoras (F2, F3, F4).

Cada accion es idempotente y registrable en AuditLog. Se invocan desde
cleanup_service.py (orquestador) o directamente via endpoint/CLI.

F2: backfill_content_hash — completa MD5 de docs sin hash
F4: backfill_emails_md — genera .md faltantes y vincula al email
F3: batch_move_mismatched, merge_identity_groups — reasignacion segura

Todas las funciones DEVUELVEN estadisticas en vez de loggearlas.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.database.models import AuditLog, Case, Document, Email
from backend.extraction.pipeline import compute_file_hash

logger = logging.getLogger("tutelas.cleanup_actions")


# ============================================================
# F2: backfill content_hash
# ============================================================

def backfill_content_hash(
    db: Session,
    batch_size: int = 100,
    dry_run: bool = False,
    progress_cb = None,
) -> dict[str, Any]:
    """Backfill MD5 hash para documents sin file_hash.

    Idempotente: skip docs que ya tienen hash.
    Commit por batches para no explotar la transaccion.

    Args:
        db: sesion SQLAlchemy
        batch_size: commit cada N docs
        dry_run: si True, no escribe nada (solo cuenta)
        progress_cb: callback(current, total) para progress

    Returns:
        dict con estadisticas: total, hashed, skipped, missing_file, errors, duration_s
    """
    start = datetime.utcnow()
    stats: dict[str, Any] = {
        "total_candidates": 0,
        "hashed": 0,
        "skipped_already_has_hash": 0,
        "missing_file_on_disk": 0,
        "empty_file_path": 0,
        "errors": 0,
        "dry_run": dry_run,
        "duration_s": 0.0,
    }

    # Candidatos: docs sin hash (empty string o NULL)
    candidates = db.query(Document).filter(
        (Document.file_hash == "") | (Document.file_hash.is_(None))
    ).all()
    stats["total_candidates"] = len(candidates)

    if not candidates:
        stats["duration_s"] = (datetime.utcnow() - start).total_seconds()
        return stats

    logger.info("F2 backfill: %d docs sin hash", len(candidates))

    processed = 0
    for doc in candidates:
        try:
            if not doc.file_path:
                stats["empty_file_path"] += 1
                processed += 1
                continue

            path = Path(doc.file_path)
            if not path.exists():
                stats["missing_file_on_disk"] += 1
                processed += 1
                continue

            file_hash = compute_file_hash(str(path))
            if not file_hash:
                stats["errors"] += 1
                processed += 1
                continue

            if not dry_run:
                doc.file_hash = file_hash
            stats["hashed"] += 1
            processed += 1

            # Commit por batches
            if not dry_run and processed % batch_size == 0:
                db.commit()
                logger.info("F2 batch commit: %d/%d", processed, len(candidates))

            if progress_cb:
                try:
                    progress_cb(processed, len(candidates))
                except Exception:
                    pass
        except Exception as e:
            logger.error("F2 error doc_id=%d: %s", doc.id, e)
            stats["errors"] += 1
            processed += 1

    # Commit final
    if not dry_run:
        db.commit()
        # AuditLog con resumen
        try:
            # case_id es NOT NULL en el schema. Usamos un case "marcador global"
            # (el primero) para entradas de cleanup que no son especificas de un caso.
            _marker_case = db.query(Case.id).first()
            _marker_id = _marker_case[0] if _marker_case else 0
            db.add(AuditLog(
                case_id=_marker_id,
                field_name="content_hash",
                action="CLEANUP_HASH",
                source="cleanup_actions:backfill_content_hash",
                new_value=f"hashed={stats['hashed']} missing_file={stats['missing_file_on_disk']} empty_path={stats['empty_file_path']}",
            ))
            db.commit()
        except Exception as e:
            logger.warning("F2 audit log write failed: %s", e)

    stats["duration_s"] = round((datetime.utcnow() - start).total_seconds(), 1)
    return stats


# ============================================================
# F4: backfill emails .md (genera .md faltantes + vincula)
# ============================================================

def backfill_emails_md(db: Session, dry_run: bool = False) -> dict[str, Any]:
    """Genera archivos .md de emails que aun no tienen uno.

    Reusa save_email_md() de gmail_monitor, que ya vincula por email_id
    gracias a F0b. Solo procesa emails con case_id asignado y body_preview.

    Idempotente: save_email_md() retorna None si el .md ya existe en disco.

    Returns:
        dict con stats: total_emails, generated, skipped_existing, errors
    """
    from backend.email.gmail_monitor import save_email_md

    start = datetime.utcnow()
    stats: dict[str, Any] = {
        "total_emails_with_case": 0,
        "generated": 0,
        "skipped_no_body": 0,
        "skipped_no_folder": 0,
        "skipped_existing_md": 0,
        "errors": 0,
        "dry_run": dry_run,
    }

    # Solo emails vinculados a caso con body_preview
    emails = db.query(Email).filter(
        Email.case_id.isnot(None),
        Email.body_preview.isnot(None),
        Email.body_preview != "",
    ).all()
    stats["total_emails_with_case"] = len(emails)

    if not emails:
        stats["duration_s"] = (datetime.utcnow() - start).total_seconds()
        return stats

    logger.info("F4 backfill: %d emails candidatos para generar .md", len(emails))

    for em in emails:
        try:
            case = db.query(Case).filter(Case.id == em.case_id).first()
            if not case or not case.folder_path:
                stats["skipped_no_folder"] += 1
                continue

            folder = Path(case.folder_path)
            if not folder.exists():
                stats["skipped_no_folder"] += 1
                continue

            if dry_run:
                stats["generated"] += 1
                continue

            date_str = em.date_received.strftime("%a, %d %b %Y %H:%M") if em.date_received else ""
            result = save_email_md(
                folder,
                {
                    "subject": em.subject or "",
                    "sender": em.sender or "",
                    "date": date_str,
                    "folder_name": case.folder_name,
                },
                em.body_preview,
                em.attachments or [],
                db=db,
                case_id=case.id,
                email_id=em.id,
                email_message_id=em.message_id,
            )
            if result:
                stats["generated"] += 1
            else:
                # save_email_md retorna None si ya existe
                stats["skipped_existing_md"] += 1
        except Exception as e:
            logger.error("F4 error email_id=%d: %s", em.id, e)
            stats["errors"] += 1

    if not dry_run:
        db.commit()
        try:
            # case_id es NOT NULL en el schema. Usamos un case "marcador global"
            # (el primero) para entradas de cleanup que no son especificas de un caso.
            _marker_case = db.query(Case.id).first()
            _marker_id = _marker_case[0] if _marker_case else 0
            db.add(AuditLog(
                case_id=_marker_id,
                field_name="emails_md",
                action="CLEANUP_EMAIL_MD",
                source="cleanup_actions:backfill_emails_md",
                new_value=f"generated={stats['generated']} existing={stats['skipped_existing_md']}",
            ))
            db.commit()
        except Exception as e:
            logger.warning("F4 audit log write failed: %s", e)

    stats["duration_s"] = round((datetime.utcnow() - start).total_seconds(), 1)
    return stats


# ============================================================
# F3: merge_identity_groups (usa la regla de identidad)
# ============================================================

def merge_identity_groups(
    db: Session,
    dry_run: bool = True,
    only_auto_mergeable: bool = True,
) -> dict[str, Any]:
    """Merge casos que comparten la misma identidad (radicado_23d + accionante + tipo_rep).

    Regla estricta: SOLO fusiona si todos los casos del grupo tienen radicado_23d
    no-vacio y coincidente. Los grupos manual_review NO se tocan.

    El caso "canonico" es el que tiene mas documents. El resto de casos mueven
    sus docs (con sibling_mover para preservar paquetes), sus emails, sus
    extractions y sus audit logs al canonico. Luego el caso duplicado queda vacio
    y se marca processing_status='DUPLICATE_MERGED'.

    Returns:
        dict con stats y lista de acciones propuestas/ejecutadas.
    """
    from backend.services.cleanup_diagnosis import diagnose
    from backend.services.sibling_mover import move_document_or_package

    start = datetime.utcnow()
    stats: dict[str, Any] = {
        "dry_run": dry_run,
        "groups_processed": 0,
        "cases_merged": 0,
        "docs_moved": 0,
        "emails_reassigned": 0,
        "errors": 0,
        "actions": [],
    }

    # Obtener grupos del diagnostico
    diag = diagnose(db)
    ig = diag.get("identity_groups", {})
    groups = ig.get("auto_mergeable", [])

    if not only_auto_mergeable:
        groups = groups + ig.get("manual_review", [])

    logger.info("F3 merge: %d grupos candidatos", len(groups))

    for group in groups:
        try:
            case_ids = group["case_ids"]
            cases = db.query(Case).filter(Case.id.in_(case_ids)).all()
            if len(cases) < 2:
                continue

            # Canonico = caso con mas documents (o el primero en caso de empate)
            canonical = max(cases, key=lambda c: (len(c.documents), -c.id))
            others = [c for c in cases if c.id != canonical.id]

            action: dict[str, Any] = {
                "group_key": f"{group.get('radicado_23d')}/{group.get('accionante')[:30]}/{group.get('tipo_representacion')}",
                "canonical_id": canonical.id,
                "canonical_folder": (canonical.folder_name or "")[:60],
                "canonical_docs_before": len(canonical.documents),
                "merge_from": [
                    {"id": c.id, "folder": (c.folder_name or "")[:60], "docs": len(c.documents)}
                    for c in others
                ],
                "docs_moved": 0,
                "emails_reassigned": 0,
            }

            if not dry_run:
                # Mover documents de cada otro al canonico
                for other in others:
                    # Snapshot de los docs antes de mover
                    other_doc_ids = [d.id for d in other.documents]
                    moved_this = 0
                    for doc_id in other_doc_ids:
                        result = move_document_or_package(
                            db, doc_id, canonical.id, reason="cleanup_merge"
                        )
                        if not result.get("errors"):
                            moved_this += len(result.get("moved_ids", []))
                    action["docs_moved"] = moved_this
                    stats["docs_moved"] += moved_this

                    # Reasignar emails del otro caso al canonico
                    emails_to_move = db.query(Email).filter(Email.case_id == other.id).all()
                    for em in emails_to_move:
                        em.case_id = canonical.id
                    action["emails_reassigned"] += len(emails_to_move)
                    stats["emails_reassigned"] += len(emails_to_move)

                    # Marcar el caso duplicado como fusionado
                    other.processing_status = "DUPLICATE_MERGED"

                    # AuditLog
                    db.add(AuditLog(
                        case_id=canonical.id,
                        field_name="merge",
                        action="CLEANUP_MERGE",
                        source="cleanup_actions:merge_identity_groups",
                        old_value=f"case_id={other.id} folder={other.folder_name[:60] if other.folder_name else ''}",
                        new_value=f"merged_into case_id={canonical.id}",
                    ))

                db.commit()
                stats["cases_merged"] += len(others)
            else:
                # En dry_run solo cuenta lo que moveria
                for other in others:
                    action["docs_moved"] += len(other.documents)
                    action["emails_reassigned"] += db.query(Email).filter(Email.case_id == other.id).count()
                stats["docs_moved"] += action["docs_moved"]
                stats["emails_reassigned"] += action["emails_reassigned"]
                stats["cases_merged"] += len(others)

            stats["actions"].append(action)
            stats["groups_processed"] += 1

        except Exception as e:
            logger.error("F3 error group %s: %s", group.get("radicado_23d"), e, exc_info=True)
            stats["errors"] += 1
            if not dry_run:
                db.rollback()

    stats["duration_s"] = round((datetime.utcnow() - start).total_seconds(), 1)
    return stats
