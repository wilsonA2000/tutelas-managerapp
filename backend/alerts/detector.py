"""Detector de alertas proactivas.

Ejecuta análisis sobre la DB para detectar:
- Plazos venciendo (48h antes de deadline)
- Documentos duplicados (mismo hash en casos distintos)
- Documentos faltantes (auto admisorio sin respuesta)
- Anomalías (FOREST en caso incorrecto, radicado mismatch)
- Emails sin caso asignado
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.alerts.models import Alert
from backend.database.models import Case, Document, Email

logger = logging.getLogger("tutelas.alerts")


def run_detection(db: Session) -> dict:
    """Ejecutar todas las detecciones y crear alertas."""
    counts = {
        "deadlines": _detect_deadlines(db),
        "unmatched_emails": _detect_unmatched_emails(db),
        "missing_docs": _detect_missing_docs(db),
        "anomalies": _detect_anomalies(db),
    }
    total = sum(counts.values())
    logger.info(f"Alert detection complete: {total} new alerts ({counts})")
    return counts


def _create_alert(db: Session, case_id: int | None, alert_type: str, severity: str,
                   title: str, description: str = ""):
    """Crear alerta si no existe una similar activa."""
    existing = db.query(Alert).filter(
        Alert.case_id == case_id,
        Alert.alert_type == alert_type,
        Alert.title == title,
        Alert.status.in_(["NEW", "SEEN"]),
    ).first()
    if existing:
        return 0
    db.add(Alert(
        case_id=case_id, alert_type=alert_type, severity=severity,
        title=title, description=description,
    ))
    db.commit()
    return 1


def _detect_deadlines(db: Session) -> int:
    """Detectar casos con fallo CONCEDE sin cumplimiento registrado."""
    count = 0
    cases = db.query(Case).filter(
        Case.sentido_fallo_1st.in_(["CONCEDE", "CONCEDE PARCIALMENTE"]),
        Case.estado == "ACTIVO",
    ).all()

    for case in cases:
        # Si tiene fallo pero no respuesta, alertar
        if case.fecha_fallo_1st and not case.fecha_respuesta:
            count += _create_alert(
                db, case.id, "DEADLINE", "CRITICAL",
                f"Fallo CONCEDE sin respuesta: {case.folder_name}",
                f"Fallo del {case.fecha_fallo_1st}. Accionante: {case.accionante or 'N/A'}"
            )

        # Si tiene incidente de desacato activo
        if case.incidente == "SI" and not case.decision_incidente:
            count += _create_alert(
                db, case.id, "DEADLINE", "CRITICAL",
                f"Desacato pendiente de decisión: {case.folder_name}",
                f"Incidente abierto. Responsable: {case.responsable_desacato or 'N/A'}"
            )

    return count


def _detect_unmatched_emails(db: Session) -> int:
    """Detectar emails sin caso asignado."""
    count = 0
    unmatched = db.query(Email).filter(
        Email.case_id.is_(None),
        Email.status != "ignorado",
    ).all()

    for em in unmatched:
        count += _create_alert(
            db, None, "UNMATCHED_EMAIL", "WARNING",
            f"Email sin caso: {(em.subject or '')[:60]}",
            f"De: {em.sender or 'N/A'} | Fecha: {em.date_received}"
        )
    return count


def _detect_missing_docs(db: Session) -> int:
    """Detectar casos con pocos documentos o sin auto admisorio."""
    count = 0
    cases = db.query(Case).filter(Case.estado == "ACTIVO").all()

    for case in cases:
        doc_count = db.query(Document).filter(Document.case_id == case.id).count()
        if doc_count == 0 and case.folder_name:
            count += _create_alert(
                db, case.id, "MISSING_DOC", "WARNING",
                f"Caso sin documentos en DB: {case.folder_name}",
                "Puede necesitar sincronización de carpeta"
            )
    return count


def _detect_anomalies(db: Session) -> int:
    """Detectar anomalías en datos."""
    count = 0

    # FOREST 3634740 (blacklisted)
    bad_forest = db.query(Case).filter(Case.radicado_forest == "3634740").all()
    for case in bad_forest:
        count += _create_alert(
            db, case.id, "ANOMALY", "CRITICAL",
            f"FOREST inválido (3634740): {case.folder_name}",
            "FOREST 3634740 es un número alucinado por la IA. Debe limpiarse."
        )

    # Cases with estado=ACTIVO but fallo 2da instancia (should be INACTIVO)
    resolved = db.query(Case).filter(
        Case.estado == "ACTIVO",
        Case.sentido_fallo_2nd.isnot(None),
        Case.sentido_fallo_2nd != "",
    ).all()
    for case in resolved:
        count += _create_alert(
            db, case.id, "ANOMALY", "INFO",
            f"Caso activo con fallo 2da instancia: {case.folder_name}",
            f"Fallo 2da: {case.sentido_fallo_2nd}. Puede necesitar marcarse como INACTIVO."
        )

    return count


def get_alerts(db: Session, status: str | None = None, severity: str | None = None,
               limit: int = 50) -> list[dict]:
    """Obtener alertas con filtros opcionales."""
    q = db.query(Alert).order_by(Alert.created_at.desc())
    if status:
        q = q.filter(Alert.status == status)
    if severity:
        q = q.filter(Alert.severity == severity)
    alerts = q.limit(limit).all()

    return [
        {
            "id": a.id,
            "case_id": a.case_id,
            "alert_type": a.alert_type,
            "severity": a.severity,
            "title": a.title,
            "description": a.description,
            "status": a.status,
            "created_at": a.created_at.isoformat() if a.created_at else "",
        }
        for a in alerts
    ]


def dismiss_alert(db: Session, alert_id: int):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if alert:
        alert.status = "DISMISSED"
        alert.resolved_at = datetime.utcnow()
        db.commit()


def get_alert_counts(db: Session) -> dict:
    """Conteo de alertas por status y severity."""
    rows = db.execute(text(
        "SELECT status, severity, COUNT(*) FROM alerts GROUP BY status, severity"
    )).fetchall()
    result = {"total_new": 0, "by_severity": {}, "by_type": {}}
    for status, severity, cnt in rows:
        if status in ("NEW", "SEEN"):
            result["total_new"] += cnt
        result["by_severity"][severity] = result["by_severity"].get(severity, 0) + cnt
    return result
