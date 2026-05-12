"""Router del dashboard."""

import os
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.services.case_service import get_dashboard_kpis, get_chart_data
from backend.services.executive_kpis import executive_dashboard
from backend.database.models import AuditLog, Case

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/kpis")
def api_kpis(db: Session = Depends(get_db)):
    return get_dashboard_kpis(db)


@router.get("/charts")
def api_charts(db: Session = Depends(get_db)):
    return get_chart_data(db)


@router.get("/executive")
def api_executive_dashboard(db: Session = Depends(get_db)):
    """v6.0 Propuesta 9.9: KPIs ejecutivos consolidados.

    Retorna un payload único con: tasa de cumplimiento, tiempos de
    respuesta, distribución de fallos, tendencia mensual, rankings
    (municipios, oficinas, abogados, accionantes recurrentes), métricas
    v6.0 (origen, estado_incidente), tasa de impugnación e integración
    con early warning (9.4).
    """
    return executive_dashboard(db)


ACTION_TYPES = {
    "AI_EXTRAER": "extract",
    "IMPORT_EMAIL": "email",
    "IMPORT_CSV": "import",
    "CREAR": "create",
    "EDICION_MANUAL": "update",
    "ACTUALIZAR": "update",
}

ACTION_LABELS = {
    "AI_EXTRAER": "IA extrajo",
    "IMPORT_EMAIL": "Email importado",
    "IMPORT_CSV": "Importado del CSV",
    "CREAR": "Caso creado",
    "EDICION_MANUAL": "Editado manualmente",
    "ACTUALIZAR": "Actualizado",
}


@router.get("/activity")
def api_recent_activity(db: Session = Depends(get_db)):
    logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(20).all()

    # Precargar folder_names
    case_ids = {l.case_id for l in logs if l.case_id}
    case_map = {}
    if case_ids:
        cases = db.query(Case.id, Case.folder_name, Case.abogado_responsable, Case.ciudad).filter(
            Case.id.in_(case_ids)
        ).all()
        case_map = {c.id: c for c in cases}

    result = []
    for l in logs:
        case = case_map.get(l.case_id)
        action = l.action or ""
        field = l.field_name or ""
        value = (l.new_value or "")[:80]

        # Construir descripcion legible
        if action == "AI_EXTRAER" and field:
            desc = f"{field}: {value}"
        elif action == "IMPORT_EMAIL":
            desc = value or "Email importado"
        elif action == "CREAR":
            desc = value or "Caso creado"
        elif action == "EDICION_MANUAL" and field:
            desc = f"{field} editado: {value}"
        else:
            desc = value or action

        # Convertir UTC a Colombia (UTC-5)
        fecha = None
        if l.timestamp:
            from datetime import timezone, timedelta
            utc_dt = l.timestamp.replace(tzinfo=timezone.utc)
            colombia_dt = utc_dt.astimezone(timezone(timedelta(hours=-5)))
            fecha = colombia_dt.isoformat()

        result.append({
            "id": l.id,
            "type": ACTION_TYPES.get(action, "update"),
            "description": desc,
            "case_folder": case.folder_name if case else None,
            "abogado": case.abogado_responsable if case else None,
            "ciudad": case.ciudad if case else None,
            "created_at": fecha,
        })

    return result

# (Modernización Fase 6) El endpoint POST /api/dashboard/chat se retiró: el chat del
# cuadro vive en /api/chat/ (router chat.py, determinístico) y lo consume el botón
# flotante "Asistente jurídico". El frontend no llamaba a /api/dashboard/chat.
