"""Herramientas jurídicas del Agente: búsqueda, análisis, generación.

Cada función decorada con @register_tool queda disponible para el agente.
El agente puede invocarlas por nombre desde lenguaje natural o desde el orchestrator.
"""

import json
import re
from datetime import datetime

from sqlalchemy.orm import Session

from backend.agent.tools.registry import register_tool
from backend.database.models import Case, Document, Email


# ============================================================
# SEARCH TOOLS
# ============================================================

@register_tool(
    name="buscar_caso",
    description="Busca casos por radicado, accionante, juzgado o texto libre",
    category="search",
    params={
        "query": "str - texto a buscar (radicado, nombre, juzgado)",
        "limit": "int - máximo resultados (default: 10)",
    },
)
def buscar_caso(db: Session, query: str, limit: int = 10) -> list[dict]:
    q = db.query(Case).filter(
        (Case.folder_name.contains(query)) |
        (Case.accionante.contains(query)) |
        (Case.radicado_23_digitos.contains(query)) |
        (Case.juzgado.contains(query)) |
        (Case.ciudad.contains(query))
    ).limit(limit).all()

    return [
        {"id": c.id, "folder": c.folder_name, "accionante": c.accionante,
         "juzgado": c.juzgado, "ciudad": c.ciudad, "estado": c.estado,
         "fallo": c.sentido_fallo_1st}
        for c in q
    ]


@register_tool(
    name="buscar_conocimiento",
    description="Búsqueda full-text en Knowledge Base (emails, PDFs, DOCX, campos)",
    category="search",
    params={
        "query": "str - texto a buscar",
        "source_type": "str - filtro: email, pdf, docx, db_field, email_md (opcional)",
    },
)
def buscar_conocimiento(db: Session, query: str, source_type: str = None) -> list[dict]:
    from backend.knowledge.search import full_text_search
    results = full_text_search(db, query, limit=15, source_type=source_type)
    return [
        {"case_id": r.case_id, "source": r.source_name, "type": r.source_type,
         "snippet": r.snippet, "rank": r.rank}
        for r in results
    ]


@register_tool(
    name="buscar_email",
    description="Busca emails por subject, remitente o contenido",
    category="search",
    params={"query": "str - texto a buscar en subject/body"},
)
def buscar_email(db: Session, query: str) -> list[dict]:
    emails = db.query(Email).filter(
        (Email.subject.contains(query)) |
        (Email.body_preview.contains(query)) |
        (Email.sender.contains(query))
    ).limit(15).all()

    return [
        {"id": e.id, "subject": e.subject, "sender": e.sender,
         "case_id": e.case_id, "status": e.status,
         "date": e.date_received.isoformat() if e.date_received else ""}
        for e in emails
    ]


# ============================================================
# ANALYSIS TOOLS
# ============================================================

@register_tool(
    name="verificar_plazo",
    description="Verifica el plazo de cumplimiento de un caso específico",
    category="analysis",
    params={"case_id": "int - ID del caso"},
    requires_case_id=True,
)
def verificar_plazo(db: Session, case_id: int) -> dict:
    from backend.intelligence.deadlines import _parse_date
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return {"error": "Caso no encontrado"}

    result = {
        "case_id": case_id,
        "folder": case.folder_name,
        "estado": case.estado,
        "fallo_1ra": case.sentido_fallo_1st,
        "fecha_fallo": case.fecha_fallo_1st,
        "impugnacion": case.impugnacion,
        "incidente": case.incidente,
        "plazo_status": "SIN PLAZO",
    }

    if case.sentido_fallo_1st in ("CONCEDE", "CONCEDE PARCIALMENTE"):
        fecha = _parse_date(case.fecha_fallo_1st)
        if fecha:
            from datetime import timedelta
            deadline = fecha + timedelta(hours=48)
            days_left = (deadline - datetime.now()).days
            result["deadline"] = deadline.isoformat()
            result["days_left"] = days_left
            result["plazo_status"] = "VENCIDO" if days_left < 0 else "URGENTE" if days_left < 3 else "EN PLAZO"

    return result


@register_tool(
    name="predecir_resultado",
    description="Predice el resultado probable de una tutela basado en datos históricos",
    category="analysis",
    params={
        "juzgado": "str - nombre parcial del juzgado (opcional)",
        "derecho": "str - derecho vulnerado (opcional)",
        "ciudad": "str - ciudad/municipio (opcional)",
    },
)
def predecir_resultado(db: Session, juzgado: str = "", derecho: str = "", ciudad: str = "") -> dict:
    from backend.intelligence.analytics import predict_outcome
    return predict_outcome(db, juzgado=juzgado, derecho=derecho, ciudad=ciudad)


@register_tool(
    name="analizar_abogado",
    description="Muestra estadísticas de rendimiento de un abogado",
    category="analysis",
    params={"nombre": "str - nombre parcial del abogado"},
)
def analizar_abogado(db: Session, nombre: str) -> dict:
    cases = db.query(Case).filter(Case.abogado_responsable.contains(nombre)).all()
    if not cases:
        return {"error": f"No se encontraron casos para '{nombre}'"}

    total = len(cases)
    activos = sum(1 for c in cases if c.estado == "ACTIVO")
    with_fallo = [c for c in cases if c.sentido_fallo_1st]
    favorables = sum(1 for c in with_fallo if c.sentido_fallo_1st in ("NIEGA", "IMPROCEDENTE"))
    desacatos = sum(1 for c in cases if c.incidente == "SI")

    return {
        "abogado": nombre,
        "total_casos": total,
        "activos": activos,
        "con_fallo": len(with_fallo),
        "favorables": favorables,
        "tasa_favorabilidad": round(favorables / max(len(with_fallo), 1) * 100, 1),
        "desacatos": desacatos,
    }


@register_tool(
    name="obtener_contexto",
    description="Obtiene el contexto completo de un caso (todos los documentos, emails, datos)",
    category="analysis",
    params={"case_id": "int - ID del caso"},
    requires_case_id=True,
)
def obtener_contexto(db: Session, case_id: int) -> dict:
    from backend.agent.context import ContextAssembler
    from backend.core.settings import settings
    assembler = ContextAssembler(db, settings.BASE_DIR)
    ctx = assembler.assemble(case_id)
    return {
        "case_id": case_id,
        "folder": ctx.folder_name,
        "known_fields": len(ctx.known_fields),
        "documents": len(ctx.documents),
        "emails": len(ctx.emails),
        "related_cases": len(ctx.related_cases),
        "tokens_estimate": ctx.total_tokens_estimate,
        "fields": ctx.known_fields,
    }


@register_tool(
    name="ver_razonamiento",
    description="Muestra la cadena de razonamiento de la última extracción de un caso",
    category="analysis",
    params={"case_id": "int - ID del caso"},
    requires_case_id=True,
)
def ver_razonamiento(db: Session, case_id: int) -> list[dict]:
    from backend.agent.reasoning import get_reasoning
    return get_reasoning(db, case_id)


# ============================================================
# MANAGEMENT TOOLS
# ============================================================

@register_tool(
    name="listar_alertas",
    description="Lista alertas activas del sistema (plazos, anomalías, emails sin caso)",
    category="management",
    params={
        "severity": "str - filtro: CRITICAL, WARNING, INFO (opcional)",
    },
)
def listar_alertas(db: Session, severity: str = None) -> list[dict]:
    from backend.alerts.detector import get_alerts
    return get_alerts(db, status="NEW", severity=severity, limit=20)


@register_tool(
    name="escanear_alertas",
    description="Ejecuta escaneo de alertas: detecta plazos vencidos, anomalías, emails sin caso",
    category="management",
)
def escanear_alertas(db: Session) -> dict:
    from backend.alerts.detector import run_detection
    return run_detection(db)


@register_tool(
    name="estadisticas_generales",
    description="Muestra estadísticas generales del sistema: casos, documentos, emails, KB",
    category="management",
)
def estadisticas_generales(db: Session) -> dict:
    total_cases = db.query(Case).count()
    activos = db.query(Case).filter(Case.estado == "ACTIVO").count()
    total_docs = db.query(Document).count()
    total_emails = db.query(Email).count()
    emails_sin_caso = db.query(Email).filter(Email.case_id.is_(None)).count()

    with_fallo = db.query(Case).filter(Case.sentido_fallo_1st.isnot(None), Case.sentido_fallo_1st != "").all()
    concede = sum(1 for c in with_fallo if c.sentido_fallo_1st in ("CONCEDE", "CONCEDE PARCIALMENTE"))
    niega = sum(1 for c in with_fallo if c.sentido_fallo_1st in ("NIEGA", "IMPROCEDENTE"))

    from backend.knowledge.search import get_stats as kb_stats
    kb = kb_stats(db)

    return {
        "casos": {"total": total_cases, "activos": activos, "inactivos": total_cases - activos},
        "documentos": total_docs,
        "emails": {"total": total_emails, "sin_caso": emails_sin_caso},
        "fallos": {"total": len(with_fallo), "concede": concede, "niega": niega,
                   "tasa_favorabilidad": round(niega / max(len(with_fallo), 1) * 100, 1)},
        "knowledge_base": kb,
    }


@register_tool(
    name="casos_por_municipio",
    description="Lista casos agrupados por municipio/ciudad",
    category="management",
    params={"ciudad": "str - filtro por ciudad (opcional)"},
)
def casos_por_municipio(db: Session, ciudad: str = "") -> list[dict]:
    from collections import Counter
    cases = db.query(Case).filter(Case.ciudad.isnot(None), Case.ciudad != "").all()
    if ciudad:
        cases = [c for c in cases if ciudad.upper() in (c.ciudad or "").upper()]

    by_city = Counter((c.ciudad or "").strip() for c in cases)
    return [{"ciudad": c, "count": n} for c, n in by_city.most_common(30)]


# ============================================================
# EXTRACTION TOOLS
# ============================================================

@register_tool(
    name="extraer_caso",
    description="Ejecuta extracción inteligente con el Agente IA v3 para un caso",
    category="extraction",
    params={"case_id": "int - ID del caso a extraer"},
    requires_case_id=True,
)
def extraer_caso(db: Session, case_id: int) -> dict:
    from backend.agent.orchestrator import smart_extract_case
    from backend.core.settings import settings
    return smart_extract_case(db, case_id, settings.BASE_DIR)


@register_tool(
    name="consumo_tokens",
    description="Muestra consumo de tokens, costo, ahorro vs APIs de pago, y tips de optimizacion",
    category="management",
)
def consumo_tokens(db: Session) -> dict:
    from backend.agent.token_manager import get_savings_report
    return get_savings_report(db)


@register_tool(
    name="validar_forest",
    description="Valida si un número FOREST es real o alucinado",
    category="extraction",
    params={"forest": "str - número FOREST a validar"},
    requires_db=False,
)
def validar_forest(forest: str) -> dict:
    from backend.agent.forest_extractor import is_valid_forest, FOREST_BLACKLIST
    is_valid = is_valid_forest(forest)
    return {
        "forest": forest,
        "valid": is_valid,
        "in_blacklist": forest in FOREST_BLACKLIST,
        "starts_with_68": forest.startswith("68"),
        "length": len(forest),
    }
