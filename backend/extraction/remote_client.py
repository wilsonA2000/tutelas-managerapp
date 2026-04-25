"""Cliente HTTP para el extraction worker remoto (RunPod pod).

Empaqueta el caso + sus archivos, hace POST al pod, recibe los updates
(case + documents + audit_logs + stats) y los aplica a la DB local. Luego
el orquestador local corre las Capas 6 (live_consolidator) y 7 (persist)
que son cross-case y pertenecen al owner de la DB.

Expone:
    - run_remote_extract(db, case) -> dict | None
      Intenta la ruta remota. Si falla o el pod no está disponible, retorna
      None para que el orquestador siga con el pipeline local como fallback.

Env vars (leídas desde settings):
    USE_REMOTE_EXTRACTION     bool (activa/desactiva el remote)
    REMOTE_EXTRACTION_URL     str  (ej. https://<pod-id>-8000.proxy.runpod.net)
    REMOTE_EXTRACTION_TOKEN   str  (bearer token del pod)
    REMOTE_EXTRACTION_TIMEOUT int  (segundos; default 600)
"""

from __future__ import annotations

import io
import json
import logging
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.orm import Session

from backend.database.models import AuditLog, Case, Document, Email


logger = logging.getLogger("tutelas.remote_client")


# ============================================================
# Config
# ============================================================

def _get_config() -> tuple[str, str, int]:
    """Retorna (url, token, timeout) desde settings. None URL → remote deshabilitado."""
    try:
        from backend.core.settings import settings
        url = str(getattr(settings, "REMOTE_EXTRACTION_URL", "") or "").rstrip("/")
        token = str(getattr(settings, "REMOTE_EXTRACTION_TOKEN", "") or "")
        timeout = int(getattr(settings, "REMOTE_EXTRACTION_TIMEOUT", 600) or 600)
        return url, token, timeout
    except Exception:
        return "", "", 600


# ============================================================
# Empaquetado del caso
# ============================================================

def _serialize_case_for_pod(case: Case) -> dict:
    """Serializa el Case a dict para enviar al pod."""
    data: dict[str, Any] = {}
    for col in Case.__table__.columns:
        if col.name in ("created_at", "updated_at"):
            continue
        val = getattr(case, col.name, None)
        if isinstance(val, datetime):
            data[col.name] = val.isoformat()
        else:
            data[col.name] = val
    return data


def _serialize_document_for_pod(doc: Document) -> dict:
    data: dict[str, Any] = {
        "id": doc.id,
        "case_id": doc.case_id,
        "filename": doc.filename,
        "file_path": doc.file_path,
        "doc_type": doc.doc_type,
        "extracted_text": doc.extracted_text,
        "extraction_method": doc.extraction_method,
        "page_count": doc.page_count,
        "file_size": doc.file_size,
        "verificacion": doc.verificacion,
        "verificacion_detalle": doc.verificacion_detalle,
        "file_hash": doc.file_hash,
        "email_id": doc.email_id,
        "email_message_id": doc.email_message_id,
        "institutional_score": doc.institutional_score,
        "visual_signature_json": doc.visual_signature_json,
    }
    if doc.extraction_date:
        data["extraction_date"] = doc.extraction_date.isoformat()
    return data


def _serialize_email_for_pod(em: Email) -> dict:
    data: dict[str, Any] = {
        "id": em.id,
        "message_id": em.message_id,
        "subject": em.subject,
        "sender": em.sender,
        "body_preview": em.body_preview,
        "status": em.status,
        "attachments": em.attachments or [],
        "in_reply_to": em.in_reply_to,
        "references_header": em.references_header,
        "match_score": em.match_score,
        "match_signals_json": em.match_signals_json,
        "match_confidence": em.match_confidence,
    }
    if em.date_received:
        data["date_received"] = em.date_received.isoformat()
    return data


def _build_zip_of_documents(documents: list[Document]) -> tuple[bytes, list[str]]:
    """Crea un ZIP en memoria con los archivos reales del caso.

    Retorna (zip_bytes, missing_filenames). missing_filenames son documentos
    cuyos file_path no existe en disco (email body_md, eliminados, etc.);
    el pod los verá como file_path inexistente y los procesará con el texto
    ya extraído si lo hay.
    """
    buffer = io.BytesIO()
    missing: list[str] = []
    seen_names: set[str] = set()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for doc in documents:
            if not doc.file_path:
                missing.append(doc.filename or f"doc_{doc.id}")
                continue
            src = Path(doc.file_path)
            if not src.exists():
                missing.append(doc.filename or src.name)
                continue
            # Evitar colisiones de nombre (mismo filename en distintos paths)
            arcname = doc.filename
            if arcname in seen_names:
                stem, ext = os.path.splitext(arcname)
                arcname = f"{stem}_{doc.id}{ext}"
            seen_names.add(arcname)
            zf.write(src, arcname=arcname)

    return buffer.getvalue(), missing


# ============================================================
# Aplicación de los updates del pod a la DB local
# ============================================================

_IMMUTABLE_CASE_FIELDS = {"id", "folder_name", "folder_path", "created_at"}


def _apply_case_updates(db: Session, case: Case, updates: dict) -> None:
    for field, value in updates.items():
        if field in _IMMUTABLE_CASE_FIELDS:
            continue
        if not hasattr(Case, field):
            continue
        setattr(case, field, value)


def _apply_documents_updates(db: Session, case: Case, updates: list[dict]) -> None:
    by_original_id = {d.id: d for d in case.documents}
    by_filename = {d.filename: d for d in case.documents}

    for upd in updates:
        original_id = upd.get("original_id")
        target = by_original_id.get(original_id) or by_filename.get(upd.get("filename"))
        if target is None:
            logger.warning("Update remoto para doc desconocido: %s", upd.get("filename"))
            continue
        for field in (
            "extracted_text", "extraction_method", "page_count", "file_size",
            "doc_type", "verificacion", "verificacion_detalle",
            "institutional_score", "visual_signature_json",
        ):
            if field in upd and upd[field] is not None:
                setattr(target, field, upd[field])
        if upd.get("extraction_date"):
            try:
                target.extraction_date = datetime.fromisoformat(upd["extraction_date"])
            except Exception:
                pass


def _apply_audit_logs(db: Session, case: Case, audit_entries: list[dict]) -> None:
    for entry in audit_entries:
        db.add(AuditLog(
            case_id=case.id,
            action=f"REMOTE_{entry.get('action', 'UNKNOWN')}",
            source=entry.get("source", "")[:500],
        ))


# ============================================================
# HTTP call
# ============================================================

def _post_case_to_pod(url: str, token: str, timeout: int,
                       meta_json: bytes, zip_bytes: bytes,
                       max_retries: int = 3) -> dict:
    """POST multipart al pod con retry ante 502/503/504/timeout.

    Raises en caso de fallo definitivo (tras agotar retries).
    """
    import time as _time
    endpoint = f"{url}/cognitive/extract-case"
    headers = {"Authorization": f"Bearer {token}"}

    last_err = None
    for attempt in range(1, max_retries + 1):
        files = {
            "meta": ("meta.json", io.BytesIO(meta_json), "application/json"),
            "docs": ("docs.zip", io.BytesIO(zip_bytes), "application/zip"),
        }
        try:
            with httpx.Client(timeout=httpx.Timeout(timeout, connect=30)) as client:
                response = client.post(endpoint, headers=headers, files=files)
                if response.status_code in (502, 503, 504):
                    last_err = httpx.HTTPStatusError(
                        f"pod transient {response.status_code}",
                        request=response.request, response=response,
                    )
                    backoff = min(30, 2 ** attempt) + (attempt * 2)
                    logger.warning(
                        "Pod %s (try %d/%d), retry en %ds",
                        response.status_code, attempt, max_retries, backoff,
                    )
                    _time.sleep(backoff)
                    continue
                response.raise_for_status()
                return response.json()
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError) as e:
            last_err = e
            backoff = min(30, 2 ** attempt) + (attempt * 2)
            logger.warning(
                "Pod timeout/conn error (try %d/%d): %s — retry en %ds",
                attempt, max_retries, type(e).__name__, backoff,
            )
            _time.sleep(backoff)
            continue

    # Agotados retries
    if last_err:
        raise last_err
    raise RuntimeError("_post_case_to_pod: fallo sin excepción capturada")


# ============================================================
# Entry point principal
# ============================================================

def run_remote_extract(db: Session, case: Case) -> dict | None:
    """Ejecuta phases 0-5 en el pod remoto + phases 6-7 localmente.

    Retorna dict con stats del pipeline completo, o None si el remote falló
    (en cuyo caso el caller debe continuar con el pipeline local como fallback).
    """
    url, token, timeout = _get_config()
    if not url or not token:
        logger.debug("Remote extraction no configurado (URL o TOKEN vacíos). Fallback.")
        return None

    case_id = case.id

    # 1. Empaquetar meta + ZIP
    try:
        meta = {
            "case": _serialize_case_for_pod(case),
            "documents": [_serialize_document_for_pod(d) for d in case.documents],
            "emails": [_serialize_email_for_pod(e) for e in (case.emails or [])],
        }
        meta_json = json.dumps(meta, ensure_ascii=False).encode("utf-8")
        zip_bytes, missing = _build_zip_of_documents(case.documents)
        logger.info(
            "Remote extract case=%d docs=%d zip=%.1fMB missing=%d",
            case_id, len(case.documents), len(zip_bytes) / 1_048_576, len(missing),
        )
        if missing:
            logger.debug("Archivos sin disco (se procesarán solo con texto previo): %s",
                         missing[:5])
    except Exception as e:
        logger.exception("No se pudo empaquetar case=%d: %s", case_id, e)
        return None

    # 2. POST al pod
    try:
        pod_response = _post_case_to_pod(url, token, timeout, meta_json, zip_bytes)
    except httpx.HTTPError as e:
        logger.exception("HTTP error llamando pod para case=%d: %s", case_id, e)
        return None
    except Exception as e:
        logger.exception("Error inesperado llamando pod para case=%d: %s", case_id, e)
        return None

    # 3. Aplicar updates a DB local
    try:
        _apply_case_updates(db, case, pod_response.get("case_updates") or {})
        _apply_documents_updates(db, case, pod_response.get("documents_updates") or [])
        _apply_audit_logs(db, case, pod_response.get("audit_logs") or [])
        db.commit()
        db.refresh(case)
    except Exception as e:
        logger.exception("Falló aplicar updates remotos a DB local case=%d: %s", case_id, e)
        db.rollback()
        return None

    # 4. Correr Capas 6-7 localmente (consolidator cross-case + persist)
    try:
        from backend.cognition.live_consolidator import consolidate_case
        from backend.cognition.cognitive_persist import persist_case

        stats = pod_response.get("stats") or {}
        stats["source"] = "remote_pod"

        consolidation = consolidate_case(db, case)
        stats["consolidation"] = consolidation.to_dict() if consolidation else None

        db.refresh(case)
        if case.processing_status == "DUPLICATE_MERGED":
            stats["status"] = "DUPLICATE_MERGED"
            return stats

        persist_report = persist_case(
            db, case,
            phase_entropies=stats.get("phase_entropies", {}),
            convergence_iterations=stats.get("iterations", 1) + 1,
        )
        stats["status"] = persist_report.status_after
        stats["entropy_final"] = persist_report.entropy_after
        return stats

    except Exception as e:
        logger.exception("Capas 6-7 locales fallaron post-remote case=%d: %s", case_id, e)
        try:
            case.processing_status = "REVISION"
            db.commit()
        except Exception:
            db.rollback()
        return {"status": "error", "case_id": case_id, "reason": str(e),
                "source": "remote_pod_phase67_failed"}
