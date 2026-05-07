"""Chat NL→DB: pregunta en lenguaje natural sobre la base depurada.

Diseño LLM-optional:
- Tier 1 — Intent classifier por keywords/regex matchea ~15 plantillas
  determinísticas que ejecutan queries parametrizadas seguras (no SQL crudo).
- Tier 2 — Si no hay match, fallback al LLM local (qwen3-4b-iuris en :8765)
  que devuelve {"template": str, "params": dict} validados antes de ejecutar.
- Sin LLM disponible: tier 1 cubre 90%+ del uso operativo.

Seguridad: NUNCA SQL libre desde LLM. Solo queries pre-aprobadas con bind params.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

import requests
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, or_, and_
from sqlalchemy.orm import Session

from backend.database.database import get_db
from backend.database.models import Case, Document, Email

logger = logging.getLogger("tutelas.chat")
router = APIRouter(prefix="/api/chat", tags=["chat"])

LLM_URL = os.getenv("LLM_LOCAL_URL", "http://127.0.0.1:8765")
LLM_MODEL = os.getenv("LLM_LOCAL_MODEL_ID", "qwen3-4b-iuris")
LLM_ENABLED = os.getenv("LLM_LOCAL_PRIMARY", "false").lower() == "true"


# ─── Schemas API ─────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    context: Optional[dict] = None


class ChatResponse(BaseModel):
    intent: str
    answer: str
    data: Optional[Any] = None
    template_used: str
    confidence: float
    llm_used: bool = False


# ─── Helpers de matching ─────────────────────────────────────────────

def _extract_first_int(text: str) -> Optional[int]:
    m = re.search(r"\b(\d{1,5})\b", text)
    return int(m.group(1)) if m else None


def _extract_municipio(text: str) -> Optional[str]:
    """Detecta municipio mencionado (lista corta de los más frecuentes)."""
    municipios = [
        "Bucaramanga", "Floridablanca", "Girón", "Giron", "Piedecuesta",
        "Barrancabermeja", "San Gil", "Vélez", "Velez", "Socorro",
        "Málaga", "Malaga", "Cimitarra", "Sabana de Torres", "Lebrija",
        "Rionegro", "Curití", "Curiti", "La Paz", "Capitanejo",
    ]
    tnorm = text.lower()
    for m in municipios:
        if m.lower() in tnorm:
            return m
    return None


def _extract_year(text: str) -> Optional[int]:
    m = re.search(r"\b(20\d{2})\b", text)
    return int(m.group(1)) if m else None


# ─── Intent templates (Tier 1: deterministas) ────────────────────────

INTENTS = []  # populated below via decorator


def intent(name: str, patterns: list[str], description: str = ""):
    """Decorator para registrar intents."""
    compiled = [re.compile(p, re.IGNORECASE) for p in patterns]

    def deco(fn):
        INTENTS.append({"name": name, "patterns": compiled, "fn": fn, "desc": description})
        return fn

    return deco


@intent("overview", [
    r"\b(resumen|estado\s+general|panorama|overview|estad[ií]sticas?)\b",
    r"\bcu[aá]ntos?\s+casos?\s+(?:hay|tenemos|existen)\b(?!\s+en)",
], description="Resumen general de la base")
def _overview(db: Session, msg: str) -> ChatResponse:
    total = db.query(Case).count()
    by_status = dict(db.query(Case.processing_status, func.count(Case.id)).group_by(Case.processing_status).all())
    by_origen = dict(db.query(Case.origen, func.count(Case.id)).group_by(Case.origen).all())
    by_inc = dict(db.query(Case.estado_incidente, func.count(Case.id))
                  .filter(Case.estado_incidente.isnot(None)).group_by(Case.estado_incidente).all())
    answer = (
        f"📊 Total: {total} casos\n\n"
        f"**Por estado de procesamiento:**\n"
        + "\n".join(f"  • {k}: {v}" for k, v in sorted(by_status.items(), key=lambda x: -x[1]))
        + f"\n\n**Por origen v6.0:**\n"
        + "\n".join(f"  • {k or 'sin clasificar'}: {v}" for k, v in sorted(by_origen.items(), key=lambda x: -x[1]))
        + f"\n\n**Por estado de incidente:**\n"
        + "\n".join(f"  • {k}: {v}" for k, v in sorted(by_inc.items(), key=lambda x: -x[1]))
    )
    return ChatResponse(intent="overview", answer=answer, data={
        "total": total, "by_status": by_status, "by_origen": by_origen, "by_incidente": by_inc,
    }, template_used="overview", confidence=0.95)


@intent("count_by_estado_incidente", [
    r"\b(?:cu[aá]ntos|cuales|qu[eé]).*\b(activos?|en\s+sanci[oó]n|cumplidos?|en\s+consulta)\b",
    r"\b(?:casos?|tutelas?|expedientes?)\s+(activos?|en\s+sanci[oó]n|cumplidos?|en\s+consulta)\b",
    r"\b(activos?|en\s+sanci[oó]n|cumplidos?)\s+(?:de\s+)?incidentes?\b",
], description="Cuántos casos por estado_incidente específico")
def _count_estado_incidente(db: Session, msg: str) -> ChatResponse:
    mapping = {
        "activo": "ACTIVO", "activos": "ACTIVO",
        "sancion": "EN_SANCION", "sanción": "EN_SANCION",
        "cumplido": "CUMPLIDO", "cumplidos": "CUMPLIDO",
        "consulta": "EN_CONSULTA",
    }
    target = None
    msg_l = msg.lower()
    for k, v in mapping.items():
        if k in msg_l:
            target = v
            break
    if not target:
        return ChatResponse(intent="count_by_estado_incidente", answer="No identifiqué qué estado.",
                            template_used="count_by_estado_incidente", confidence=0.4)
    n = db.query(Case).filter(Case.estado_incidente == target).count()
    samples = db.query(Case.id, Case.folder_name).filter(Case.estado_incidente == target).limit(5).all()
    sample_str = "\n".join(f"  • #{cid}: {fn}" for cid, fn in samples)
    answer = f"🚨 **{n} casos en estado `{target}`**\n\nMuestra:\n{sample_str}"
    return ChatResponse(intent="count_by_estado_incidente", answer=answer,
                        data={"estado": target, "count": n, "samples": [{"id": s[0], "folder": s[1]} for s in samples]},
                        template_used="count_by_estado_incidente", confidence=0.9)


@intent("cases_by_municipio", [
    r"\b(?:tutelas?|casos?)\s+(?:de|en)\s+(?:la\s+ciudad\s+de\s+)?([A-ZÁÉÍÓÚ][\wáéíóúñÑ\s]+?)(?:\?|\.|$)",
    r"\bmunicipio\s+(?:de\s+)?([A-ZÁÉÍÓÚ][\wáéíóúñÑ\s]+)",
], description="Casos por municipio/ciudad")
def _cases_by_municipio(db: Session, msg: str) -> ChatResponse:
    muni = _extract_municipio(msg)
    if not muni:
        return ChatResponse(intent="cases_by_municipio", answer="No identifiqué el municipio.",
                            template_used="cases_by_municipio", confidence=0.3)
    n = db.query(Case).filter(Case.ciudad.ilike(f"%{muni}%")).count()
    samples = db.query(Case.id, Case.folder_name, Case.accionante).filter(
        Case.ciudad.ilike(f"%{muni}%")).limit(5).all()
    sample_str = "\n".join(
        f"  • #{cid}: {(fn or 'sin nombre')[:50]} ({(acc or '')[:40]})"
        for cid, fn, acc in samples
    )
    answer = f"🏛️ **{n} casos en {muni}**\n\nÚltimos:\n{sample_str}"
    return ChatResponse(intent="cases_by_municipio", answer=answer,
                        data={"municipio": muni, "count": n, "samples": [
                            {"id": s[0], "folder": s[1], "accionante": s[2]} for s in samples]},
                        template_used="cases_by_municipio", confidence=0.85)


@intent("case_detail", [
    r"\b(?:caso|expediente|detalle\s+(?:del\s+)?caso?)\s+(?:n[uú]mero\s+|#)?(\d{1,5})\b",
    r"\b(?:info|información|información\s+de(?:l)?\s+caso?)\s+(?:caso\s+)?(\d{1,5})\b",
], description="Detalle de un caso por ID")
def _case_detail(db: Session, msg: str) -> ChatResponse:
    cid = _extract_first_int(msg)
    if not cid:
        return ChatResponse(intent="case_detail", answer="No identifiqué el ID del caso.",
                            template_used="case_detail", confidence=0.3)
    case = db.query(Case).filter(Case.id == cid).first()
    if not case:
        return ChatResponse(intent="case_detail", answer=f"No encontré el caso #{cid}.",
                            template_used="case_detail", confidence=0.9)
    docs_n = db.query(Document).filter(Document.case_id == cid).count()
    answer = (
        f"📁 **Caso #{cid}**: {case.folder_name}\n\n"
        f"  • Estado: {case.processing_status}\n"
        f"  • Origen: {case.origen or '?'}\n"
        f"  • Estado incidente: {case.estado_incidente or 'N/A'}\n"
        f"  • Accionante: {(case.accionante or '?')[:80]}\n"
        f"  • Accionados: {(case.accionados or '?')[:120]}\n"
        f"  • Juzgado 1ra: {case.juzgado or '?'}\n"
        f"  • Juzgado 2da: {case.juzgado_2nd or '—'}\n"
        f"  • Sentido fallo 1ra: {case.sentido_fallo_1st or '?'}\n"
        f"  • Impugnación: {case.impugnacion or '?'} | quien_impugno: {case.quien_impugno or '—'}\n"
        f"  • Ciudad: {case.ciudad or '?'}\n"
        f"  • Documentos: {docs_n}"
    )
    return ChatResponse(intent="case_detail", answer=answer,
                        data={"id": cid, "folder": case.folder_name, "status": case.processing_status,
                              "origen": case.origen, "documents_count": docs_n},
                        template_used="case_detail", confidence=0.95)


@intent("search_accionante", [
    r"\b(?:casos?|tutelas?|expedientes?)\s+(?:de|del?|por)\s+([A-ZÁÉÍÓÚ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚ][a-záéíóúñ]+){1,4})\b",
    r"\bbuscar?\s+([A-ZÁÉÍÓÚ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚ][a-záéíóúñ]+)+)",
], description="Buscar casos por nombre del accionante")
def _search_accionante(db: Session, msg: str) -> ChatResponse:
    # Captura nombre con mayúsculas iniciales (NO "Bucaramanga" sola — exige 2+ tokens)
    m = re.search(r"\b([A-ZÁÉÍÓÚ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚ][a-záéíóúñ]+){1,4})\b", msg)
    if not m:
        return ChatResponse(intent="search_accionante", answer="No identifiqué el nombre.",
                            template_used="search_accionante", confidence=0.3)
    name = m.group(1).strip()
    # No confundir con municipios
    if _extract_municipio(name):
        return ChatResponse(intent="search_accionante", answer="Parece municipio, no nombre.",
                            template_used="search_accionante", confidence=0.3)
    cases = db.query(Case).filter(Case.accionante.ilike(f"%{name}%")).limit(10).all()
    if not cases:
        return ChatResponse(intent="search_accionante",
                            answer=f"No encontré casos con accionante '{name}'.",
                            template_used="search_accionante", confidence=0.85)
    sample = "\n".join(f"  • #{c.id} {c.folder_name[:60]} — {c.processing_status}" for c in cases)
    answer = f"👤 **{len(cases)} casos** con '{name}':\n\n{sample}"
    return ChatResponse(intent="search_accionante", answer=answer,
                        data={"name": name, "count": len(cases),
                              "cases": [{"id": c.id, "folder": c.folder_name, "status": c.processing_status} for c in cases]},
                        template_used="search_accionante", confidence=0.85)


@intent("pending_impugnacion", [
    r"\b(?:impugnaciones?|apelaciones?)\s+(?:pendientes?|sin\s+fallo)\b",
    r"\b(?:casos?|tutelas?)\s+(?:con\s+)?impugnaci[oó]n\s+(?:pendiente|sin\s+resolver)\b",
    r"\bsin\s+(?:fallo\s+(?:de\s+)?)?segunda\s+instancia\b",
], description="Casos con impugnación SI pero sin fallo de 2da instancia")
def _pending_impugnacion(db: Session, msg: str) -> ChatResponse:
    cases = db.query(Case).filter(
        Case.impugnacion == "SI",
        or_(Case.sentido_fallo_2nd.is_(None), Case.sentido_fallo_2nd == "")
    ).all()
    sample = "\n".join(
        f"  • #{c.id} {c.folder_name[:55]} (juzgado_2nd: {(c.juzgado_2nd or '?')[:35]})"
        for c in cases[:10]
    )
    answer = f"⏳ **{len(cases)} casos con impugnación pendiente** (sin fallo 2da):\n\n{sample}"
    return ChatResponse(intent="pending_impugnacion", answer=answer,
                        data={"count": len(cases),
                              "cases": [{"id": c.id, "folder": c.folder_name} for c in cases[:50]]},
                        template_used="pending_impugnacion", confidence=0.9)


@intent("top_accionados", [
    r"\b(?:m[aá]s|top)\s+(?:demandad[oa]s?|accionad[oa]s?|denunciad[oa]s?)\b",
    r"\b(?:cu[aá]les?|qu[eé])\s+entidades?\s+(?:son\s+)?m[aá]s\s+(?:demandad[oa]s?|accionad[oa]s?)\b",
    r"\bentidades?\s+(?:m[aá]s\s+)?(?:demandad[oa]s?|frecuentes?)\b",
], description="Entidades más accionadas")
def _top_accionados(db: Session, msg: str) -> ChatResponse:
    rows = db.query(Case.accionados, func.count(Case.id)).filter(
        Case.accionados.isnot(None), Case.accionados != ""
    ).group_by(Case.accionados).order_by(func.count(Case.id).desc()).limit(10).all()
    if not rows:
        return ChatResponse(intent="top_accionados", answer="Sin datos.",
                            template_used="top_accionados", confidence=0.5)
    body = "\n".join(f"  {i+1:>2}. {(a or '')[:65]:<65} — {n}" for i, (a, n) in enumerate(rows))
    return ChatResponse(intent="top_accionados", answer=f"🏢 **Top accionados**:\n\n{body}",
                        data={"top": [{"accionado": a, "count": n} for a, n in rows]},
                        template_used="top_accionados", confidence=0.85)


@intent("list_en_sancion", [
    r"\b(?:lista|listar|mu[eé]strame|cu[aá]les)\s+.*\bsanci[oó]n\b",
    r"\bcasos?\s+(?:en\s+)?sanci[oó]n\s+(?:lista|completa|todos?)\b",
], description="Listado completo de casos en sanción")
def _list_en_sancion(db: Session, msg: str) -> ChatResponse:
    cases = db.query(Case.id, Case.folder_name, Case.accionante, Case.juzgado).filter(
        Case.estado_incidente == "EN_SANCION"
    ).order_by(Case.id).all()
    body = "\n".join(
        f"  #{cid} {(fn or '')[:50]:<50} | {(acc or '')[:35]:<35} | {(jzg or '')[:30]}"
        for cid, fn, acc, jzg in cases
    )
    return ChatResponse(intent="list_en_sancion",
                        answer=f"⚠️ **{len(cases)} casos EN SANCIÓN**:\n\n```\n{body}\n```",
                        data={"count": len(cases),
                              "cases": [{"id": c[0], "folder": c[1], "accionante": c[2], "juzgado": c[3]} for c in cases]},
                        template_used="list_en_sancion", confidence=0.9)


@intent("monthly_trends", [
    r"\b(?:tutelas?|casos?)\s+(?:por|en|durante)\s+mes(?:es)?\b",
    r"\btendencias?\s+mensual(?:es)?\b",
    r"\bevoluci[oó]n\s+(?:mensual|temporal)\b",
], description="Distribución mensual de casos")
def _monthly_trends(db: Session, msg: str) -> ChatResponse:
    from sqlalchemy import text as sa_text
    # fecha_ingreso formato DD/MM/YYYY → extraer YYYY-MM
    rows = db.execute(sa_text(
        "SELECT substr(fecha_ingreso, 7, 4) || '-' || substr(fecha_ingreso, 4, 2) AS mes, "
        "COUNT(*) as n FROM cases WHERE fecha_ingreso IS NOT NULL "
        "AND fecha_ingreso != '' AND length(fecha_ingreso) >= 10 "
        "GROUP BY mes ORDER BY mes DESC LIMIT 12"
    )).fetchall()
    if not rows:
        return ChatResponse(intent="monthly_trends",
                            answer="No hay datos de fecha_ingreso suficientes.",
                            template_used="monthly_trends", confidence=0.5)
    body = "\n".join(f"  • {mes}: {n} casos" for mes, n in rows)
    return ChatResponse(intent="monthly_trends",
                        answer=f"📅 **Tendencia mensual (últimos 12 meses)**:\n\n{body}",
                        data={"months": [{"mes": m, "count": n} for m, n in rows]},
                        template_used="monthly_trends", confidence=0.85)


# ─── Intents v8.2: Para gobernador/jefes ──────────────────────────────

@intent("count_by_abogado", [
    r"\b(?:cu[aá]ntos?\s+)?casos?\s+(?:tiene|por|de|maneja)\s+(?:cada\s+)?abogad[oa]\b",
    r"\bcarga\s+(?:de|por)\s+abogad[oa]s?\b",
    r"\b(?:reparto|distribuci[oó]n)\s+(?:de\s+)?cas[ao]s\s+(?:por|entre)\s+abogad[oa]s?\b",
    r"\bqui[eé]n\s+tiene\s+m[aá]s\s+casos?\b",
], description="Distribución de casos por abogado canónico")
def _count_by_abogado(db: Session, msg: str) -> ChatResponse:
    rows = db.query(Case.abogado_canonical, func.count(Case.id)).filter(
        Case.processing_status == "COMPLETO"
    ).group_by(Case.abogado_canonical).order_by(func.count(Case.id).desc()).all()
    body = "\n".join(
        f"  • {(a or 'SIN ASIGNAR'):40s}  {n} casos"
        for a, n in rows
    )
    return ChatResponse(intent="count_by_abogado",
                        answer=f"👥 **Casos por abogado**:\n\n{body}",
                        data={"abogados": [{"abogado": a, "count": n} for a, n in rows]},
                        template_used="count_by_abogado", confidence=0.9)


@intent("resumen_abogado_detalle", [
    r"\b(?:cu[aá]ntos|qu[eé])\s+casos?\s+(?:tiene|maneja)\s+(\w+)\b",
    r"\b(?:carga|portafolio)\s+de\s+(\w+)\b",
    r"\bqu[eé]\s+tiene\s+(\w+)\b",
], description="Detalle por abogado específico")
def _resumen_abogado_detalle(db: Session, msg: str) -> ChatResponse:
    # Detectar nombre del abogado en el mensaje
    msg_l = msg.lower()
    SHORTS = {
        "victor": "VICTOR ALFONSO COLMENARES NIÑO",
        "angelica": "ANGELICA YADIRA BARROSO SARMIENTO",
        "angelia": "ANGELICA YADIRA BARROSO SARMIENTO",
        "otilia": "OTILIA LUNA LOPEZ",
        "juan diego": "JUAN DIEGO CRUZ LIZCANO",
        "diego": "JUAN DIEGO CRUZ LIZCANO",
        "jhon": "JHON ALEXANDER BOHORQUEZ CAMARGO",
        "john": "JHON ALEXANDER BOHORQUEZ CAMARGO",
        "luis eduardo": "LUIS EDUARDO MEZA JURADO",
        "luis": "LUIS EDUARDO MEZA JURADO",
        "fernando": "FERNANDO MAURICIO CAMACHO PICO",
        "wilson": "WILSON ANDRES ARGUELLO CASTELLANOS",
        "maria cristina": "MARIA CRISTINA VILLAMIZAR SCHILLER",
        "cristina": "MARIA CRISTINA VILLAMIZAR SCHILLER",
        "diego otilio": "DIEGO OTILIO RODRIGUEZ NUÑEZ",
        "jorge": "JORGE JAVIER SEPULVEDA JAIMES",
    }
    target = None
    for k, full in sorted(SHORTS.items(), key=lambda x: -len(x[0])):
        if k in msg_l:
            target = full
            break
    if not target:
        return ChatResponse(intent="resumen_abogado_detalle",
                            answer="¿De qué abogado? Ej: VICTOR, ANGELICA, OTILIA, JUAN DIEGO, JHON, LUIS EDUARDO, FERNANDO, MARIA CRISTINA, etc.",
                            template_used="resumen_abogado_detalle", confidence=0.4)

    cases = db.query(Case).filter(
        Case.processing_status == "COMPLETO",
        Case.abogado_canonical == target,
    ).all()
    by_estado = {}
    by_origen = {}
    en_sancion = 0
    incidente_activo = 0
    fallos_concede = 0
    for c in cases:
        by_estado[c.estado_incidente or "N/A"] = by_estado.get(c.estado_incidente or "N/A", 0) + 1
        by_origen[c.origen or "?"] = by_origen.get(c.origen or "?", 0) + 1
        if c.estado_incidente == "EN_SANCION":
            en_sancion += 1
        elif c.estado_incidente == "ACTIVO":
            incidente_activo += 1
        if (c.sentido_fallo_1st or "").upper().startswith("CONCEDE"):
            fallos_concede += 1

    answer = (
        f"👤 **{target}**\n\n"
        f"**Carga total:** {len(cases)} casos\n\n"
        f"**Por origen:**\n" + "\n".join(f"  • {k}: {v}" for k, v in sorted(by_origen.items(), key=lambda x: -x[1])) + "\n\n"
        f"**Estado incidente:**\n" + "\n".join(f"  • {k}: {v}" for k, v in sorted(by_estado.items(), key=lambda x: -x[1])) + "\n\n"
        f"⚠️ **Críticos:**\n"
        f"  • EN SANCIÓN: {en_sancion}\n"
        f"  • Incidente activo: {incidente_activo}\n"
        f"  • Fallos CONCEDE pendientes: {fallos_concede}"
    )
    return ChatResponse(intent="resumen_abogado_detalle", answer=answer,
                        data={"abogado": target, "total": len(cases),
                              "en_sancion": en_sancion,
                              "incidente_activo": incidente_activo,
                              "fallos_concede": fallos_concede,
                              "by_estado": by_estado, "by_origen": by_origen},
                        template_used="resumen_abogado_detalle", confidence=0.9)


@intent("count_by_dependencia", [
    r"\b(?:cu[aá]ntos?\s+)?casos?\s+(?:por|de)\s+depend[ei]ncia\b",
    r"\bcarga\s+(?:de|por)\s+depend[ei]ncia\b",
    r"\bcasos?\s+de\s+(talento\s+humano|estrat[eé]gica|financiera|cobertura|inspecci[oó]n|tesorer[ií]a|permanencia|pae|atenci[oó]n|nomina)\b",
], description="Casos por dependencia SED")
def _count_by_dependencia(db: Session, msg: str) -> ChatResponse:
    # Si menciona dependencia específica, filtrar
    DEP_MAP = {
        "talento humano": "DIRECCION_TALENTO_DOCENTE",
        "estrategica": "DIRECCION_ESTRATEGICA",
        "estratégica": "DIRECCION_ESTRATEGICA",
        "financiera": "FINANCIERA",
        "cobertura": "COBERTURA_EDUCATIVA",
        "inspeccion": "INSPECCION_VIGILANCIA",
        "inspección": "INSPECCION_VIGILANCIA",
        "tesoreria": "EQUIPO_TESORERIA",
        "tesorería": "EQUIPO_TESORERIA",
        "permanencia": "DIRECCION_PERMANENCIA",
        "pae": "DIRECCION_PERMANENCIA",
        "atencion": "ATENCION_CIUDADANO",
        "atención": "ATENCION_CIUDADANO",
        "nomina": "NOMINA",
        "nómina": "NOMINA",
    }
    msg_l = msg.lower()
    target = None
    for k, code in sorted(DEP_MAP.items(), key=lambda x: -len(x[0])):
        if k in msg_l:
            target = code
            break

    if target:
        q = db.query(Case).filter(
            Case.processing_status == "COMPLETO",
            Case.dependencia_canonical == target,
        )
        total = q.count()
        cases = q.limit(20).all()
        body = "\n".join(
            f"  • #{c.id} {(c.folder_name or '')[:55]} | "
            f"{(c.abogado_canonical or '-').split()[0] if c.abogado_canonical else '-'}"
            for c in cases
        )
        more = f"\n\n  ... y {total - 20} más (total {total})" if total > 20 else ""
        return ChatResponse(intent="count_by_dependencia",
                            answer=f"🏢 **{total} casos en {target}**:\n\n{body}{more}",
                            data={"dependencia": target, "count": total},
                            template_used="count_by_dependencia", confidence=0.9)
    # Sin filtro: distribución total
    rows = db.query(Case.dependencia_canonical, func.count(Case.id)).filter(
        Case.processing_status == "COMPLETO"
    ).group_by(Case.dependencia_canonical).order_by(func.count(Case.id).desc()).all()
    body = "\n".join(f"  • {(d or 'SIN ASIGNAR'):30s}  {n}" for d, n in rows)
    return ChatResponse(intent="count_by_dependencia",
                        answer=f"🏢 **Casos por dependencia**:\n\n{body}",
                        data={"dependencias": [{"dep": d, "count": n} for d, n in rows]},
                        template_used="count_by_dependencia", confidence=0.85)


@intent("alertas_resumen", [
    r"\b(?:cu[aá]ntos?|cu[aá]l)\s+(?:casos?|tutelas?)?\s*(?:rojos?|cr[ií]ticos?|urgentes?)\b",
    r"\balertas?\s+(?:tempranas?|rojas?)\b",
    r"\b(?:sem[aá]foro|riesgo|criticidad)\b",
], description="Resumen de alertas tempranas (ROJO/AMARILLO)")
def _alertas_resumen(db: Session, msg: str) -> ChatResponse:
    from datetime import datetime
    from backend.alerts.early_warning import score_case
    cases = db.query(Case).filter(Case.processing_status == "COMPLETO").all()
    now = datetime.utcnow()
    counts = {"ROJO": 0, "AMARILLO": 0, "VERDE": 0, "N/A": 0}
    rojos_top = []
    for c in cases:
        r = score_case(c, now)
        counts[r.level] = counts.get(r.level, 0) + 1
        if r.level == "ROJO":
            rojos_top.append((c.id, c.folder_name, r.score, c.abogado_canonical))
    rojos_top.sort(key=lambda x: -x[2])
    answer = (
        f"🚨 **Alertas tempranas**\n\n"
        f"  • 🔴 ROJOS (intervención inmediata): {counts['ROJO']}\n"
        f"  • 🟡 AMARILLOS (vigilar): {counts['AMARILLO']}\n"
        f"  • 🟢 VERDES (en regla): {counts['VERDE']}\n"
        f"  • ⚪ N/A: {counts.get('N/A', 0)}\n\n"
        f"**Top 5 críticos:**\n"
        + "\n".join(f"  • #{cid} {(f or '')[:50]} (score {s:.2f}) — {(a or 'sin asignar').split()[0] if a else 'SIN'}"
                    for cid, f, s, a in rojos_top[:5])
    )
    return ChatResponse(intent="alertas_resumen", answer=answer, data=counts,
                        template_used="alertas_resumen", confidence=0.92)


@intent("count_by_sentido_fallo", [
    r"\b(?:cu[aá]ntos?|qu[eé])\s+(?:fallos?|sentencias?|casos?)\s+(?:concede|niega|conceden|niegan|improcedente|amparados?|favorables?|desfavorables?)\b",
    r"\bcasos?\s+(?:con\s+)?fallo\s+(concede|niega|improcedente|favorable|desfavorable)\b",
    r"\b(?:distribuci[oó]n|sentido)\s+(?:de\s+)?(?:los\s+)?fallos?\b",
], description="Casos por sentido de fallo 1ra/2da")
def _count_by_sentido_fallo(db: Session, msg: str) -> ChatResponse:
    msg_l = msg.lower()
    target = None
    if any(k in msg_l for k in ("concede", "conceden", "favorable", "amparad")):
        target = "CONCEDE"
    elif any(k in msg_l for k in ("niega", "niegan", "desfavorable")):
        target = "NIEGA"
    elif "improcedente" in msg_l:
        target = "IMPROCEDENTE"

    rows = db.query(Case.sentido_fallo_1st, func.count(Case.id)).filter(
        Case.processing_status == "COMPLETO",
        Case.sentido_fallo_1st.isnot(None),
        Case.sentido_fallo_1st != "",
    ).group_by(Case.sentido_fallo_1st).order_by(func.count(Case.id).desc()).all()

    if target:
        q = db.query(Case).filter(
            Case.processing_status == "COMPLETO",
            Case.sentido_fallo_1st.ilike(f"%{target}%"),
        )
        total = q.count()
        cases = q.limit(15).all()
        body = "\n".join(
            f"  • #{c.id} {(c.folder_name or '')[:55]} | "
            f"{(c.abogado_canonical or '-').split()[0] if c.abogado_canonical else '-'}"
            for c in cases
        )
        more = f"\n\n  ... y {total - 15} más (total {total})" if total > 15 else ""
        return ChatResponse(intent="count_by_sentido_fallo",
                            answer=f"⚖️ **{total} fallos {target}**:\n\n{body}{more}",
                            data={"target": target, "count": total},
                            template_used="count_by_sentido_fallo", confidence=0.9)
    body = "\n".join(f"  • {k}: {v}" for k, v in rows)
    return ChatResponse(intent="count_by_sentido_fallo",
                        answer=f"⚖️ **Distribución de fallos 1ra instancia:**\n\n{body}",
                        data=[{"sentido": k, "count": v} for k, v in rows],
                        template_used="count_by_sentido_fallo", confidence=0.88)


@intent("plazos_proximos", [
    r"\b(?:fallos?|cumplimientos?|plazos?)\s+(?:por\s+vencer|pr[oó]ximos?|que\s+vencen|urgentes?)\b",
    r"\b(?:cu[aá]ndo|qu[eé]\s+plazos?)\s+vencen?\b",
    r"\bvencimientos?\b",
], description="Plazos de cumplimiento próximos a vencer")
def _plazos_proximos(db: Session, msg: str) -> ChatResponse:
    from backend.database.models import ComplianceTracking
    from datetime import datetime
    rows = db.query(ComplianceTracking).filter(
        ComplianceTracking.estado != "CUMPLIDO"
    ).all()
    now = datetime.utcnow()
    vencidos, urgentes, por_vencer, en_plazo = [], [], [], []
    for r in rows:
        fl = r.fecha_limite or ""
        # Parse DD/MM/YYYY
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", fl)
        if not m: continue
        try:
            limite = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError: continue
        d = (limite - now).days
        case = db.query(Case).filter(Case.id == r.case_id).first()
        item = (r.case_id, case.folder_name if case else "?", d, r.fecha_limite)
        if d < 0: vencidos.append(item)
        elif d <= 3: urgentes.append(item)
        elif d <= 7: por_vencer.append(item)
        else: en_plazo.append(item)
    answer = (
        f"⏰ **Plazos de cumplimiento**\n\n"
        f"  • 🔴 Vencidos: {len(vencidos)}\n"
        f"  • 🟠 Urgentes (<3 días): {len(urgentes)}\n"
        f"  • 🟡 Por vencer (<7 días): {len(por_vencer)}\n"
        f"  • 🟢 En plazo: {len(en_plazo)}\n\n"
    )
    if vencidos:
        answer += "**Vencidos:**\n" + "\n".join(
            f"  • #{cid} {(f or '')[:50]} ({abs(d)}d vencido)"
            for cid, f, d, _ in sorted(vencidos, key=lambda x: x[2])[:5]
        ) + "\n"
    if urgentes:
        answer += "\n**Urgentes:**\n" + "\n".join(
            f"  • #{cid} {(f or '')[:50]} (vence en {d}d)"
            for cid, f, d, _ in sorted(urgentes, key=lambda x: x[2])[:5]
        )
    return ChatResponse(intent="plazos_proximos", answer=answer,
                        data={"vencidos": len(vencidos), "urgentes": len(urgentes),
                              "por_vencer": len(por_vencer), "en_plazo": len(en_plazo)},
                        template_used="plazos_proximos", confidence=0.9)


@intent("temas_top", [
    r"\b(?:cu[aá]les|qu[eé])\s+(?:son\s+)?(?:los\s+)?(?:temas?|asuntos?|materias?)\s+(?:m[aá]s|principales?|frecuentes?|comunes?)\b",
    r"\btop\s+(?:temas?|asuntos?)\b",
    r"\b(?:tem[aá]tic[ao]|categor[ií]as?\s+tem[aá]tic[ao]s?)\b",
], description="Top temas/asuntos de las tutelas")
def _temas_top(db: Session, msg: str) -> ChatResponse:
    rows = db.query(Case.categoria_tematica, func.count(Case.id)).filter(
        Case.processing_status == "COMPLETO",
        Case.categoria_tematica.isnot(None),
        Case.categoria_tematica != "",
    ).group_by(Case.categoria_tematica).order_by(func.count(Case.id).desc()).limit(15).all()
    if not rows:
        return ChatResponse(intent="temas_top",
                            answer="No hay datos de categoría temática.",
                            template_used="temas_top", confidence=0.4)
    body = "\n".join(f"  • {(t or '?')[:50]:50s}  {n}" for t, n in rows)
    return ChatResponse(intent="temas_top",
                        answer=f"🏷️ **Top temas:**\n\n{body}",
                        data=[{"tema": t, "count": n} for t, n in rows],
                        template_used="temas_top", confidence=0.85)


@intent("ayuda", [
    r"^\s*(?:ayuda|help|qu[eé]\s+puedo\s+preguntar|c[oó]mo\s+funciona|qu[eé]\s+sabes)\s*\??\s*$",
    r"\bqu[eé]\s+(?:tipos?|clases?)\s+de\s+preguntas?\b",
], description="Ayuda — qué se puede preguntar")
def _ayuda(db: Session, msg: str) -> ChatResponse:
    return ChatResponse(intent="ayuda",
                        answer=(
                            "👋 **Asistente jurídico — Tutelas Santander**\n\n"
                            "Puedes preguntarme sobre:\n\n"
                            "📊 **Estadísticas generales**\n"
                            "  • cuántos casos hay\n"
                            "  • resumen / panorama\n\n"
                            "🚨 **Alertas y críticos**\n"
                            "  • cuántos rojos / críticos\n"
                            "  • casos en sanción\n"
                            "  • incidentes activos\n"
                            "  • plazos por vencer\n\n"
                            "👥 **Por abogado**\n"
                            "  • casos por abogado\n"
                            "  • carga de Victor / Angelica / Otilia / Juan Diego / etc.\n\n"
                            "🏢 **Por dependencia**\n"
                            "  • casos de talento humano\n"
                            "  • casos de financiera\n"
                            "  • carga por dependencia\n\n"
                            "⚖️ **Por sentido**\n"
                            "  • cuántos fallos concede\n"
                            "  • distribución de fallos\n\n"
                            "🏷️ **Temas y asuntos**\n"
                            "  • top temas\n"
                            "  • categorías temáticas\n\n"
                            "📅 **Tendencias**\n"
                            "  • casos por mes\n"
                            "  • tendencia mensual\n\n"
                            "🔍 **Búsqueda**\n"
                            "  • caso 142 / detalle del caso N\n"
                            "  • buscar accionante NOMBRE\n"
                            "  • casos en Bucaramanga\n"
                        ),
                        template_used="ayuda", confidence=1.0)


# ─── Tier 2: LLM fallback ────────────────────────────────────────────

def _llm_intent_fallback(message: str) -> Optional[dict]:
    """Pide al LLM que identifique template + params. Retorna None si falla.

    Si llama-server está pausado (post-extraction), lo relanza lazy.
    """
    if not LLM_ENABLED:
        return None
    # Lazy restart si llama-server está pausado
    try:
        from backend.services.llm_mutex import ensure_llm_up, PAUSE_FLAG
        if PAUSE_FLAG.exists():
            logger.info("LLM pausado — relanzando lazy")
            if not ensure_llm_up(wait_s=45):
                logger.warning("LLM no arrancó — fallback a unknown")
                return None
    except Exception as e:
        logger.debug("ensure_llm_up falló: %s", e)
    template_list = ", ".join(i["name"] for i in INTENTS)
    prompt = (
        f"Eres un router de intención. Templates disponibles: {template_list}.\n"
        f"Mensaje del usuario: \"{message}\"\n"
        f"Responde SOLO JSON: {{\"template\": \"<nombre>\", \"params\": {{...}}}}\n"
        f"Si ningún template aplica: {{\"template\": null}}"
    )
    try:
        r = requests.post(
            f"{LLM_URL}/v1/chat/completions",
            json={"model": LLM_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 200, "temperature": 0.1},
            timeout=10,
        )
        r.raise_for_status()
        import json
        text = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception as e:
        logger.debug("LLM fallback failed: %s", str(e)[:80])
    return None


# ─── Endpoint principal ──────────────────────────────────────────────

@router.post("/", response_model=ChatResponse)
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    msg = req.message.strip()
    if not msg:
        return ChatResponse(intent="empty", answer="Escribe una pregunta.",
                            template_used="none", confidence=0.0)

    # Tier 1: keyword matching
    # Estrategia: probar cada intent. Si confidence>=0.5, retornar.
    # Si confidence<0.5 (e.g., regex matchea pero extracción falló), seguir
    # buscando otros intents que puedan tener mejor match.
    best_low_conf = None
    for it in INTENTS:
        for pat in it["patterns"]:
            if pat.search(msg):
                logger.info("chat intent=%s msg=%r", it["name"], msg[:60])
                resp = it["fn"](db, msg)
                if resp.confidence >= 0.5:
                    return resp
                if best_low_conf is None or resp.confidence > best_low_conf.confidence:
                    best_low_conf = resp
                break  # un solo pattern por intent

    # Tier 2: LLM fallback (si está disponible)
    llm_result = _llm_intent_fallback(msg)
    if llm_result and llm_result.get("template"):
        for it in INTENTS:
            if it["name"] == llm_result["template"]:
                logger.info("chat LLM-routed intent=%s", it["name"])
                resp = it["fn"](db, msg)
                resp.llm_used = True
                return resp

    # Si hubo match parcial low-conf, retornarlo (mejor que nada)
    if best_low_conf is not None:
        return best_low_conf

    # Sin match
    available = ", ".join(f"`{i['name']}`" for i in INTENTS)
    return ChatResponse(
        intent="unknown",
        answer=(f"No identifiqué la intención. Templates disponibles:\n\n{available}\n\n"
                f"Ejemplos: \"resumen\", \"casos en sanción\", \"caso 119\", \"tutelas en Bucaramanga\""),
        template_used="none", confidence=0.0,
    )


@router.get("/intents")
def list_intents():
    """Lista los intents disponibles + sus patrones (debug/UI)."""
    return [
        {
            "name": it["name"],
            "description": it["desc"],
            "examples": [p.pattern for p in it["patterns"][:2]],
        } for it in INTENTS
    ]


@router.get("/health")
def chat_health():
    """Estado del chat: disponible siempre, LLM opcional."""
    llm_status = "disabled"
    if LLM_ENABLED:
        try:
            r = requests.get(f"{LLM_URL}/v1/models", timeout=2)
            llm_status = "up" if r.status_code == 200 else "down"
        except Exception:
            llm_status = "down"
    return {
        "tier1_intents": len(INTENTS),
        "tier2_llm": llm_status,
        "llm_url": LLM_URL,
        "model": LLM_MODEL,
    }
