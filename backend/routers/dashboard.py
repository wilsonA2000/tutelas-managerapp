"""Router del dashboard."""

import os
from fastapi import APIRouter, Depends
from pydantic import BaseModel
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


# ============================================================
# Chat IA — consultas en lenguaje natural sobre tutelas
# ============================================================

class ChatRequest(BaseModel):
    question: str


def _build_cases_context(db: Session) -> str:
    """Construir resumen tabular de todos los casos para el prompt de IA."""
    cases = db.query(Case).filter(
        Case.folder_name.isnot(None), Case.folder_name != "None", Case.folder_name != "",
        Case.processing_status != "DUPLICATE_MERGED",
    ).all()

    # KPIs resumidos
    kpis = get_dashboard_kpis(db)
    charts = get_chart_data(db)

    summary = f"""RESUMEN GENERAL:
- Total casos: {kpis['total']}
- Activos: {kpis['activos']}, Inactivos: {kpis['inactivos']}
- Fallos: CONCEDE {kpis['concede']}, NIEGA {kpis['niega']}, IMPROCEDENTE {kpis['improcedente']}, Sin fallo {kpis['sin_fallo']}
- Con impugnacion: {kpis['con_impugnacion']}, Con incidente desacato: {kpis['con_incidente']}
- Completitud de datos: {kpis['completitud']}%

TOP DERECHOS VULNERADOS:
""" + "\n".join(f"- {d['derecho']}: {d['count']} casos" for d in charts.get('by_desfavorable', [])[:10])

    summary += "\n\nTOP CIUDADES:\n" + "\n".join(f"- {c['ciudad']}: {c['count']} casos" for c in charts['by_city'][:10])
    summary += "\n\nTOP OFICINAS:\n" + "\n".join(f"- {o['oficina']}: {o['count']} casos" for o in charts.get('by_oficina', [])[:10])
    summary += "\n\nFALLOS DESFAVORABLES (CONCEDE) POR DERECHO:\n" + "\n".join(f"- {d['derecho']}: {d['count']} fallos desfavorables" for d in charts.get('by_desfavorable', [])[:10])

    # Tabla de casos (campos clave, no todo)
    summary += "\n\nDETALLE DE CASOS (radicado | accionante | ciudad | derecho | fallo | estado | oficina | impugnacion | incidente):\n"
    for c in cases:
        row = f"{c.folder_name or ''} | {(c.accionante or '')[:30]} | {c.ciudad or ''} | {(c.derecho_vulnerado or '')[:40]} | {c.sentido_fallo_1st or ''} | {c.estado or ''} | {(c.oficina_responsable or '')[:30]} | {c.impugnacion or ''} | {c.incidente or ''}"
        summary += row + "\n"

    return summary


@router.post("/chat")
def api_chat(req: ChatRequest, db: Session = Depends(get_db)):
    """Chat en lenguaje natural sobre las tutelas usando IA."""
    # Redirigir al Agent Runner (usa Smart Router multi-modelo)
    try:
        import backend.agent.tools.legal_tools  # noqa: F401 — register tools
        from backend.agent.runner import run_agent
        result = run_agent(db, req.question)
        # Format answer for chat
        answer = result.get("answer", "")
        if not answer and result.get("steps"):
            parts = []
            for step in result["steps"]:
                if step.get("result", {}).get("result"):
                    res = step["result"]["result"]
                    if isinstance(res, dict):
                        for k, v in list(res.items())[:8]:
                            val = str(v)[:100] if not isinstance(v, dict) else str(v)[:100]
                            parts.append(f"**{k}**: {val}")
                    elif isinstance(res, list):
                        parts.append(f"{len(res)} resultados encontrados")
            answer = "\n".join(parts) if parts else "Consulta procesada sin resultados visibles"
        return {"response": answer, "error": False}
    except Exception as e:
        return {"response": f"Error del agente: {str(e)[:200]}", "error": True}
