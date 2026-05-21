"""Helper para registrar eventos en audit_log.

Es la fuente única de eventos del historial del expediente: creación,
modificación, traslado de documentos, cambios de estado de compliance, etc.

Uso típico:
    from backend.services.audit_service import audit_event

    audit_event(
        db,
        case_id=case.id,
        action='COMPLIANCE_STATE_CHANGED',
        actor='wilson',
        entity_type='compliance',
        entity_id=compliance_row.id,
        field_name='estado',
        old_value='VENCIDO',
        new_value='EN_PROCESO',
        description='Estado cambiado VENCIDO → EN_PROCESO (TERCERO 1ra)',
        meta={'ordinal_nombre': 'TERCERO', 'instancia': '1ra'},
    )

NO duplica filas existentes de audit_log — solo agrega filas nuevas con la
nomenclatura completa. Las 780 filas históricas (sin entity_*/description/
meta_json) se renderizan en el modal usando action + field_name + values.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.database.models import AuditLog


# Catálogo de event_types — usá las constantes en lugar de strings sueltos
# para mantener consistencia con los filtros del modal Historial.

# Génesis del expediente
EVT_CASE_CREATED          = "CASE_CREATED"
EVT_CASE_FOLDER_RENAMED   = "CASE_FOLDER_RENAMED"
EVT_CASE_ACUMULADO        = "CASE_ACUMULADO"
EVT_CASE_DELETED          = "CASE_DELETED"

# Documentos
EVT_DOC_ADDED             = "DOC_ADDED"
EVT_DOC_REMOVED           = "DOC_REMOVED"
EVT_DOC_MOVED             = "DOC_MOVED"
EVT_DOC_TYPE_CHANGED      = "DOC_TYPE_CHANGED"
EVT_DOC_VERIFICATION      = "DOC_VERIFICATION_CHANGED"
EVT_DOC_EXTRACTED         = "DOC_EXTRACTED"

# Campos extraídos
EVT_FIELD_EXTRACTED       = "FIELD_EXTRACTED"
EVT_FIELD_MODIFIED        = "FIELD_MODIFIED"
EVT_EXTRACTION_RUN        = "EXTRACTION_RUN"

# Compliance / órdenes
EVT_COMPLIANCE_CREATED    = "COMPLIANCE_CREATED"
EVT_COMPLIANCE_STATE      = "COMPLIANCE_STATE_CHANGED"
EVT_COMPLIANCE_NOTE       = "COMPLIANCE_NOTE_ADDED"
EVT_COMPLIANCE_EVIDENCE   = "COMPLIANCE_EVIDENCE_LINKED"

# Correos
EVT_EMAIL_RECEIVED        = "EMAIL_RECEIVED"
EVT_EMAIL_LINKED          = "EMAIL_LINKED"
EVT_EMAIL_UNLINKED        = "EMAIL_UNLINKED"

# Procesales (detectados)
EVT_INCIDENTE_DETECTED    = "INCIDENTE_DETECTED"
EVT_IMPUGNACION_DETECTED  = "IMPUGNACION_DETECTED"
EVT_FALLO_DETECTED        = "FALLO_DETECTED"


def audit_event(
    db: Session,
    *,
    case_id: int,
    action: str,
    actor: Optional[str] = "system",
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    field_name: Optional[str] = None,
    old_value: Any = None,
    new_value: Any = None,
    description: Optional[str] = None,
    meta: Optional[dict] = None,
    commit: bool = True,
) -> AuditLog:
    """Registra un evento en audit_log.

    Args:
        db: Sesión SQLAlchemy.
        case_id: ID del expediente (requerido).
        action: event_type del catálogo (EVT_*). Usar las constantes.
        actor: quien produjo el evento — 'wilson' | 'system' | 'gmail_monitor' |
               'ai_deepseek' | 'v9_regex' | nombre de usuario futuro.
        entity_type: tipo de objeto afectado (case|document|email|compliance|field).
        entity_id: id del objeto (ej. compliance_tracking.id, document.id).
        field_name: campo modificado (cuando aplica).
        old_value / new_value: valores antes/después. Se convierten a str.
        description: frase human-readable. Si no se da, la UI la construye.
        meta: dict con contexto adicional. Se serializa a JSON.
        commit: si True, hace commit. Útil pasarlo False cuando audit_event
                se llama dentro de una transacción mayor.

    Returns:
        El AuditLog creado.
    """
    entry = AuditLog(
        case_id=case_id,
        action=action,
        source=actor,
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field_name,
        old_value=None if old_value is None else str(old_value)[:2000],
        new_value=None if new_value is None else str(new_value)[:2000],
        description=description,
        meta_json=json.dumps(meta, ensure_ascii=False, default=str) if meta else None,
    )
    db.add(entry)
    if commit:
        db.commit()
        db.refresh(entry)
    return entry
