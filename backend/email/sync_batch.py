"""Sync histórico batcheable de Gmail para el experimento v5.5.

Nueva función `check_inbox_batch()` que:
- Lee Gmail con query custom (default: `in:inbox`) y paginación explícita.
- Procesa un lote de N mensajes (default 100) y retorna métricas detalladas.
- Soporta `GMAIL_READ_ONLY=true` para NO marcar emails como leído (preserva
  el estado de Gmail entre sesiones del experimento).
- Usa el matcher v5.4.4 completo (multi-criterio + threading + rad_utils).

Diseñado para uso manual controlado:
    curl -X POST /api/emails/sync-batch -d '{"batch_size": 100}'
    # inspeccionar metrics, filesystem, DB
    curl -X POST /api/emails/sync-batch -d '{"batch_size": 100, "resume_cursor": "<next>"}'

NO toca `check_inbox()` de producción (sigue siendo el flujo "is:unread" normal).
"""

from __future__ import annotations

import base64
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from backend.core.settings import settings
from backend.database.models import AuditLog, Case, Document, Email
from backend.email.case_lookup_cache import get_cache
from backend.email.gmail_monitor import (
    _extract_body_complete,
    _find_attachment_parts,
    _get_gmail_service,
    _normalize_typos,
    _should_ignore,
    classify_email_type,
    create_new_case,
    download_attachments,
    extract_accionante,
    extract_forest,
    extract_radicado,
    match_to_case,
    save_email_md,
    update_case_fields,
)
from backend.email.matcher import EmailSignals, resolve_thread_parent, score_case_match
from backend.email.rad_utils import reconcile as rad_reconcile

logger = logging.getLogger("tutelas.sync_batch")


# ─────────────────────────────────────────────────────────────
# Contador global de progreso (singleton por proceso)
# ─────────────────────────────────────────────────────────────

_CUMULATIVE: dict = {
    "total_processed": 0,
    "total_auto_match": 0,
    "total_quarantine": 0,
    "total_new_case": 0,
    "total_errors": 0,
    "total_ignored": 0,
    "total_duplicate_gmail": 0,
    "total_folders_created": 0,
    "total_attachments": 0,
    "total_md_files": 0,
    "last_batch_ts": None,
    "last_cursor": None,
}


def get_cumulative() -> dict:
    """Retorna copia del acumulado actual."""
    return dict(_CUMULATIVE)


def reset_cumulative() -> None:
    """Resetea el acumulado (llamar al empezar un nuevo experimento)."""
    for k in _CUMULATIVE:
        _CUMULATIVE[k] = 0 if isinstance(_CUMULATIVE[k], int) else None


# ─────────────────────────────────────────────────────────────
# Core: procesar un email en modo experimento
# ─────────────────────────────────────────────────────────────


def _process_one_message(
    db: Session,
    service,
    msg_ref: dict,
    existing_ids: set,
    read_only: bool,
) -> dict:
    """Procesa un mensaje de Gmail. Retorna dict con métricas del email.

    Categorías de resultado (clave `result`):
        - DUPLICATE_GMAIL: ya existía message_id en DB
        - IGNORED: filtro _should_ignore (subjects/senders no-jurídicos)
        - AUTO_MATCH: matcher HIGH (score≥70) → case_id asignado
        - QUARANTINE: matcher MEDIUM (40-69) → email.status=AMBIGUO
        - NEW_CASE: sin match confiable → create_new_case
        - SALIENTE: email saliente del usuario → no se crea caso
        - NO_SIGNAL: sin señales ni rad_corto → email queda huérfano
        - ERROR: excepción
    """
    result = {"result": "UNKNOWN", "subject": "", "folder": None, "adjuntos": 0, "md_created": False}

    try:
        msg = service.users().messages().get(
            userId="me", id=msg_ref["id"], format="full"
        ).execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        message_id = headers.get("Message-ID", headers.get("Message-Id", msg_ref["id"]))

        if message_id in existing_ids:
            # Modo experiment: si ya lo procesamos, no marcamos nada (idempotente)
            result["result"] = "DUPLICATE_GMAIL"
            return result

        subject = _normalize_typos(headers.get("Subject", ""))
        sender = headers.get("From", "")
        date_str = headers.get("Date", "")
        in_reply_to_hdr = headers.get("In-Reply-To", "") or headers.get("In-reply-to", "")
        references_hdr = headers.get("References", "") or headers.get("references", "")
        result["subject"] = subject[:80]

        if _should_ignore(subject, sender):
            result["result"] = "IGNORED"
            return result

        # Parsear fecha
        try:
            from email.utils import parsedate_to_datetime
            from datetime import timezone
            dt = parsedate_to_datetime(date_str)
            date_received = dt.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            date_received = datetime.utcnow()

        body = _extract_body_complete(msg.get("payload", {}))
        att_parts = _find_attachment_parts(msg.get("payload", {}))
        att_names = [a["filename"] for a in att_parts]

        full_text = f"{subject} {body}"
        tipo = classify_email_type(subject, sender)
        radicado_data = extract_radicado(full_text)
        forest = extract_forest(body, att_names)
        radicado_data["forest"] = forest
        accionante = extract_accionante(subject, body)

        try:
            from backend.agent.regex_library import CC_ACCIONANTE
            cc_m = CC_ACCIONANTE.pattern.search(f"{subject}\n{body[:5000]}")
            if cc_m:
                radicado_data["cc_accionante"] = cc_m.group(1)
        except Exception:
            pass

        # Reconcile rad23 ↔ rad_corto (fix zfill bug)
        _rc23, _rc_corto = rad_reconcile(
            radicado_data.get("radicado_23", ""),
            radicado_data.get("radicado_corto", ""),
        )
        radicado_data["radicado_23"] = _rc23
        radicado_data["radicado_corto"] = _rc_corto

        # Thread parent
        thread_parent_case_id = None
        if in_reply_to_hdr or references_hdr:
            try:
                thread_parent_case_id = resolve_thread_parent(
                    db, in_reply_to_hdr, references_hdr
                )
            except Exception as e:
                logger.debug("thread_parent lookup fail: %s", e)

        # Matcher multi-criterio
        cache = get_cache()
        signals = EmailSignals(
            rad23=radicado_data.get("radicado_23", ""),
            rad_corto=radicado_data.get("radicado_corto", ""),
            forest=forest,
            cc_accionante=radicado_data.get("cc_accionante", ""),
            accionante_name=accionante,
            sender=sender,
            thread_parent_case_id=thread_parent_case_id,
        )

        case = None
        match_score = 0
        match_confidence = "NONE"
        match_signals_json = None
        accion = "NEW_CASE"

        if tipo == "SALIENTE":
            result["result"] = "SALIENTE"
            # No crear caso, pero registrar email
            _persist_email(
                db, message_id, subject, sender, date_received, body,
                None, "PENDIENTE", in_reply_to_hdr, references_hdr,
                match_score, match_confidence, match_signals_json,
                service, msg_ref, att_parts,  # desc adjuntos al _emails_sin_clasificar
                read_only,
            )
            return result
        elif signals.has_any() and cache.is_built:
            match = score_case_match(db, cache, signals)
            match_score = match.score
            match_confidence = match.confidence
            match_signals_json = match.to_signals_json()

            if match.is_auto_match:
                case = db.query(Case).filter(Case.id == match.case_id).first()
                accion = "AUTO_MATCH"
            elif match.confidence == "MEDIUM":
                case = None
                accion = "QUARANTINE"

        if accion == "NEW_CASE" and not case:
            # Crear caso solo si tenemos señales mínimas (rad_corto o forest)
            if radicado_data.get("radicado_corto") or forest:
                case = create_new_case(db, radicado_data, accionante)
                if case:
                    accion = "NEW_CASE"
                    result["folder"] = case.folder_name
                    try:
                        cache.refresh_one(db, case.id)
                    except Exception:
                        pass
                else:
                    accion = "NO_SIGNAL"
            else:
                accion = "NO_SIGNAL"

        result["result"] = accion

        # Persistir email + docs
        _persist_email(
            db, message_id, subject, sender, date_received, body,
            case,
            "ASIGNADO" if case else ("AMBIGUO" if accion == "QUARANTINE" else "PENDIENTE"),
            in_reply_to_hdr, references_hdr,
            match_score, match_confidence, match_signals_json,
            service, msg_ref, att_parts,
            read_only,
            accionante=accionante,
            radicado_data=radicado_data,
            forest=forest,
            tipo=tipo,
            adjuntos_result=result,
        )

        return result

    except Exception as e:
        logger.error("Error procesando email %s: %s", msg_ref.get("id"), e, exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        result["result"] = "ERROR"
        result["error"] = str(e)[:200]
        return result


def _persist_email(
    db, message_id, subject, sender, date_received, body,
    case, status, in_reply_to_hdr, references_hdr,
    match_score, match_confidence, match_signals_json,
    service, msg_ref, att_parts,
    read_only,
    accionante: str = "",
    radicado_data: Optional[dict] = None,
    forest: str = "",
    tipo: str = "",
    adjuntos_result: Optional[dict] = None,
) -> None:
    """Crea registro Email + descarga adjuntos + guarda .md + update_case_fields."""
    email_record = Email(
        message_id=message_id, subject=subject, sender=sender,
        date_received=date_received, body_preview=body or "",
        case_id=case.id if case else None,
        attachments=[],
        status=status,
        processed_at=datetime.utcnow(),
        in_reply_to=in_reply_to_hdr or None,
        references_header=references_hdr or None,
        match_score=match_score or None,
        match_confidence=match_confidence if match_confidence != "NONE" else None,
        match_signals_json=match_signals_json,
    )
    db.add(email_record)
    db.flush()

    # Adjuntos
    guardados, ignorados = download_attachments(
        service, msg_ref["id"], case, db,
        email_id=email_record.id,
        email_message_id=message_id,
    )
    email_record.attachments = guardados
    if adjuntos_result is not None:
        adjuntos_result["adjuntos"] = len(guardados)

    # .md
    if case and case.folder_path and body:
        from email.utils import format_datetime
        md_name = save_email_md(
            Path(case.folder_path),
            {
                "subject": subject, "sender": sender,
                "date": date_received.isoformat() if date_received else "",
                "folder_name": case.folder_name,
            },
            body, guardados,
            db=db, case_id=case.id,
            email_id=email_record.id,
            email_message_id=message_id,
        )
        if md_name and adjuntos_result is not None:
            adjuntos_result["md_created"] = True

    # Actualizar campos del caso
    if case and radicado_data is not None:
        data = {**radicado_data, "forest": forest, "accionante": accionante}
        update_case_fields(db, case, tipo, data)
        db.add(AuditLog(
            case_id=case.id, action="IMPORT_EMAIL_SYNC_BATCH",
            source="sync_batch_v55",
            new_value=f"Email: {subject[:100]}",
        ))

    # Marcar leído en Gmail solo si NO es read_only
    if not read_only:
        try:
            service.users().messages().modify(
                userId="me", id=msg_ref["id"],
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
# Entrypoint batch
# ─────────────────────────────────────────────────────────────


def check_inbox_batch(
    db: Session,
    batch_size: int = 100,
    resume_cursor: Optional[str] = None,
    query: Optional[str] = None,
    read_only: bool = True,
) -> dict:
    """Procesa un batch de mensajes de Gmail con paginación explícita.

    Args:
        db: Session SQLAlchemy
        batch_size: cuántos emails procesar (default 100)
        resume_cursor: pageToken de Gmail para retomar donde se quedó
        query: query Gmail (default: settings.GMAIL_HISTORICAL_QUERY o "in:inbox")
        read_only: si True, NO marca emails como leído en Gmail

    Returns:
        dict con métricas del batch + cursor_token para el siguiente.
    """
    effective_query = query or settings.GMAIL_HISTORICAL_QUERY or "in:inbox"
    service = _get_gmail_service()

    # Lista paginada
    list_kwargs = {
        "userId": "me",
        "q": effective_query,
        "maxResults": batch_size,
    }
    if resume_cursor:
        list_kwargs["pageToken"] = resume_cursor
    response = service.users().messages().list(**list_kwargs).execute()
    messages = response.get("messages", [])
    next_cursor = response.get("nextPageToken")
    total_estimated = response.get("resultSizeEstimate", 0)

    existing_ids = {e.message_id for e in db.query(Email.message_id).all()}

    # Contador de este batch
    batch_stats = {
        "batch_size_requested": batch_size,
        "emails_in_batch": len(messages),
        "AUTO_MATCH": 0,
        "QUARANTINE": 0,
        "NEW_CASE": 0,
        "NO_SIGNAL": 0,
        "IGNORED": 0,
        "DUPLICATE_GMAIL": 0,
        "SALIENTE": 0,
        "ERROR": 0,
        "new_folders": [],
        "attachments_downloaded": 0,
        "md_files_created": 0,
        "errors_detail": [],
        "quarantine_detail": [],  # casos MEDIUM con sugerencia
    }

    import time
    t0 = time.time()

    for i, msg_ref in enumerate(messages, 1):
        result = _process_one_message(db, service, msg_ref, existing_ids, read_only)
        cat = result["result"]
        batch_stats[cat] = batch_stats.get(cat, 0) + 1
        batch_stats["attachments_downloaded"] += result.get("adjuntos", 0)
        if result.get("md_created"):
            batch_stats["md_files_created"] += 1
        if result.get("folder"):
            batch_stats["new_folders"].append(result["folder"])
        if cat == "ERROR":
            batch_stats["errors_detail"].append({
                "subject": result["subject"],
                "error": result.get("error", ""),
            })
        # Commit por email para no perder progreso si algo revienta después
        try:
            db.commit()
        except Exception as commit_err:
            logger.error("commit fail: %s", commit_err)
            db.rollback()

    elapsed = round(time.time() - t0, 1)
    batch_stats["elapsed_seconds"] = elapsed
    batch_stats["emails_per_second"] = round(len(messages) / elapsed, 2) if elapsed > 0 else 0

    # Actualizar cumulative
    _CUMULATIVE["total_processed"] += len(messages)
    _CUMULATIVE["total_auto_match"] += batch_stats["AUTO_MATCH"]
    _CUMULATIVE["total_quarantine"] += batch_stats["QUARANTINE"]
    _CUMULATIVE["total_new_case"] += batch_stats["NEW_CASE"]
    _CUMULATIVE["total_errors"] += batch_stats["ERROR"]
    _CUMULATIVE["total_ignored"] += batch_stats["IGNORED"]
    _CUMULATIVE["total_duplicate_gmail"] += batch_stats["DUPLICATE_GMAIL"]
    _CUMULATIVE["total_folders_created"] += len(batch_stats["new_folders"])
    _CUMULATIVE["total_attachments"] += batch_stats["attachments_downloaded"]
    _CUMULATIVE["total_md_files"] += batch_stats["md_files_created"]
    _CUMULATIVE["last_batch_ts"] = datetime.utcnow().isoformat()
    _CUMULATIVE["last_cursor"] = next_cursor

    return {
        "batch": batch_stats,
        "cumulative": dict(_CUMULATIVE),
        "cursor_token": next_cursor,
        "paused": True,
        "remaining_estimated": max(0, total_estimated - _CUMULATIVE["total_processed"]),
        "has_more": next_cursor is not None,
    }
