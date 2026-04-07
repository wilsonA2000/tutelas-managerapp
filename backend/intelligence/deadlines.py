"""Gestión de plazos legales y calendario de vencimientos."""

import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from backend.database.models import Case

logger = logging.getLogger("tutelas.deadlines")

# Plazos legales estándar en Colombia (días hábiles)
PLAZO_RESPUESTA_TUTELA = 2  # días hábiles para contestar
PLAZO_FALLO_1RA = 10  # días hábiles para fallar
PLAZO_IMPUGNACION = 3  # días hábiles para impugnar
PLAZO_CUMPLIMIENTO = 48  # horas para cumplir fallo


def get_calendar_events(db: Session) -> list[dict]:
    """Obtener eventos de calendario con plazos."""
    events = []
    cases = db.query(Case).filter(Case.estado == "ACTIVO").all()

    for case in cases:
        folder = case.folder_name or f"Caso {case.id}"

        # Fallo CONCEDE sin cumplimiento
        if case.sentido_fallo_1st in ("CONCEDE", "CONCEDE PARCIALMENTE"):
            fecha_fallo = _parse_date(case.fecha_fallo_1st)
            if fecha_fallo and not case.fecha_respuesta:
                deadline = fecha_fallo + timedelta(hours=PLAZO_CUMPLIMIENTO)
                days_left = (deadline - datetime.now()).days
                severity = "VENCIDO" if days_left < 0 else "URGENTE" if days_left < 3 else "EN_PLAZO"
                events.append({
                    "case_id": case.id,
                    "folder_name": folder,
                    "accionante": case.accionante or "",
                    "event_type": "CUMPLIMIENTO_FALLO",
                    "deadline": deadline.isoformat(),
                    "days_left": days_left,
                    "severity": severity,
                    "description": f"Cumplir fallo {case.sentido_fallo_1st} del {case.fecha_fallo_1st}",
                })

        # Incidente de desacato abierto
        if case.incidente == "SI" and case.fecha_apertura_incidente:
            fecha_inc = _parse_date(case.fecha_apertura_incidente)
            if fecha_inc and not case.decision_incidente:
                events.append({
                    "case_id": case.id,
                    "folder_name": folder,
                    "accionante": case.accionante or "",
                    "event_type": "DESACATO_PENDIENTE",
                    "deadline": fecha_inc.isoformat(),
                    "days_left": (datetime.now() - fecha_inc).days * -1,
                    "severity": "URGENTE",
                    "description": f"Desacato abierto desde {case.fecha_apertura_incidente}",
                })

        # Impugnación pendiente de resolución
        if case.impugnacion == "SI" and not case.sentido_fallo_2nd:
            events.append({
                "case_id": case.id,
                "folder_name": folder,
                "accionante": case.accionante or "",
                "event_type": "IMPUGNACION_PENDIENTE",
                "deadline": None,
                "days_left": None,
                "severity": "INFO",
                "description": f"Impugnación sin resolver. Juzgado 2da: {case.juzgado_2nd or 'N/A'}",
            })

    # Sort by severity priority
    severity_order = {"VENCIDO": 0, "URGENTE": 1, "EN_PLAZO": 2, "INFO": 3}
    events.sort(key=lambda e: severity_order.get(e["severity"], 4))

    return events


def get_deadline_summary(db: Session) -> dict:
    """Resumen de plazos para dashboard."""
    events = get_calendar_events(db)
    summary = {
        "total": len(events),
        "vencidos": sum(1 for e in events if e["severity"] == "VENCIDO"),
        "urgentes": sum(1 for e in events if e["severity"] == "URGENTE"),
        "en_plazo": sum(1 for e in events if e["severity"] == "EN_PLAZO"),
        "info": sum(1 for e in events if e["severity"] == "INFO"),
    }
    return summary


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None
