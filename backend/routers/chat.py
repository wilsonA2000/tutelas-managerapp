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
from backend.core.time import utcnow

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
# El fallback LLM del chat (router + respuesta libre) se activa solo si
# LLM_LOCAL_PRIMARY=true Y NO está puesto V9_DISABLE_LLM=true. En equipos justos de RAM
# se arranca el backend con V9_DISABLE_LLM=true → el chat queda 100% Tier-1 (instantáneo);
# quita esa variable para habilitar el asistente con el modelo local.
LLM_ENABLED = (
    os.getenv("LLM_LOCAL_PRIMARY", "false").lower() == "true"
    and os.getenv("V9_DISABLE_LLM", "false").lower() != "true"
)


# ─── Conocimiento del cuadro (las 18 columnas que extrae v9 + vocabularios) ──────
# Fuente única: backend/v9/types.EXCEL_FIELDS. Aquí solo añadimos una descripción
# humana por columna para que el asistente pueda explicar "qué tiene el cuadro".
_FIELD_DESCRIPTIONS: dict[str, str] = {
    "radicado_23_digitos": "radicado judicial de 23 dígitos",
    "radicado_forest": "número FOREST interno de la SED",
    "tipo_actuacion": "TUTELA o INCIDENTE",
    "accionante": "quien interpone la tutela (persona o personería municipal)",
    "accionados": "entidades demandadas (por defecto Gobernación + Secretaría de Educación)",
    "vinculados": "terceros vinculados al trámite",
    "derecho_vulnerado": "derecho(s) fundamental(es) invocado(s)",
    "categoria_tematica": "agrupación temática del caso (grupo L2 de la SED)",
    "juzgado": "juzgado de primera instancia",
    "ciudad": "municipio del juzgado de 1ra (≈ lugar de los hechos)",
    "fecha_ingreso": "fecha del auto que admite la tutela (DD/MM/AAAA)",
    "asunto": "qué pide la tutela, en vocabulario controlado (TRASLADO, NOMBRAMIENTO, …)",
    "pretensiones": "transcripción literal de lo solicitado en el escrito de tutela",
    "oficina_responsable": "Dirección de la SED responsable del asunto de fondo",
    "abogado_responsable": "abogado del Grupo Jurídico que firma la respuesta",
    "estado": "ACTIVO o INACTIVO (derivado del estado procesal)",
    "fecha_respuesta": "fecha del oficio de respuesta de la SED",
    "sentido_fallo_1st": "sentido del fallo de 1ra (CONCEDE, NIEGA, IMPROCEDENTE, …)",
    "fecha_fallo_1st": "fecha del fallo de 1ra",
    "impugnacion": "SI / NO — si hubo recurso de impugnación",
    "quien_impugno": "ACCIONANTE, ACCIONADO, MINISTERIO_PUBLICO o AMBOS",
    "forest_impugnacion": "FOREST de la impugnación",
    "juzgado_2nd": "juzgado/tribunal de 2da instancia",
    "sentido_fallo_2nd": "sentido del fallo de 2da (CONFIRMA, REVOCA, MODIFICA, …)",
    "fecha_fallo_2nd": "fecha del fallo de 2da",
    "incidente": "SI / NO — si hubo incidente de desacato",
    "fecha_apertura_incidente": "fecha de apertura del incidente",
    "responsable_desacato": "funcionario contra quien va el incidente",
    "decision_incidente": "SANCIONA, NO_SANCIONA, NIEGA_APERTURA, CIERRA o EN_TRAMITE",
    "incidente_2": "2º incidente de desacato (SI/NO) — más sus 3 campos análogos",
    "incidente_3": "3er incidente de desacato (SI/NO) — más sus 3 campos análogos",
    "observaciones": "notas (agente oficioso, medida provisional, sujeto de especial protección, …)",
}

# Marco normativo que el asistente debe poder citar (reciclado del prompt v8).
_LEGAL_CONTEXT = (
    "Marco normativo aplicable a estas tutelas (cita lo que corresponda):\n"
    "- Acción de tutela: art. 86 Constitución + Decreto 2591/1991. Plazo de respuesta de la entidad: el que fije el juez (típico 2-3 días).\n"
    "- Cumplimiento del fallo: 48 horas (art. 27 Decreto 2591/1991) o el plazo que ordene la sentencia.\n"
    "- Impugnación del fallo: art. 31 Decreto 2591/1991, plazo 3 días desde la notificación; la conoce el superior funcional (art. 32).\n"
    "- Incidente de desacato: art. 52 Decreto 2591/1991. Si el juez decreta sanción, hay grado de consulta (revisión automática del superior).\n"
    "- Carencia actual de objeto / hecho superado: art. 26 Decreto 2591/1991.\n"
    "- Reparto: Decreto 1983/2017 — las tutelas contra autoridades departamentales se reparten en 1ra instancia a Jueces Municipales del lugar de los hechos; en 2da suben al Juez del Circuito (factor funcional, Auto 269/19 Corte Const.); las de Juez del Circuito suben al Tribunal Superior (o Tribunal Administrativo si la 1ra fue un Juzgado Administrativo del Circuito).\n"
    "- Organigrama SED Santander (Decretos 544/2021 y 048/2022): 5 Direcciones L1 (TALENTO_DOCENTE, ESTRATEGICA, PERMANENCIA, ADMIN_FINANCIERA, APOYO_DIRECTO), varios grupos L2, algunos equipos L3."
)


def _cuadro_vocab_lines() -> str:
    """Vocabularios controlados de los campos del cuadro (para el prompt del LLM)."""
    try:
        from backend.v9.field_extractor import (
            DERECHO_VOCAB, SENTIDO_FALLO_VOCAB, SENTIDO_FALLO_2DA_VOCAB,
            QUIEN_IMPUGNO_VOCAB, DECISION_INCIDENTE_VOCAB,
        )
        from backend.cognition.legal_schema import CATEGORIA_TEMATICA_VOCAB
        return (
            f"- derecho_vulnerado ∈ {{{', '.join(DERECHO_VOCAB)}}} (se concatenan varios con ' - ')\n"
            f"- asunto ∈ vocabulario SED (TRASLADO, REINTEGRO, NOMBRAMIENTO, PENSION, CESANTIAS, MATRICULA, INCLUSION_DISCAPACIDAD, TRANSPORTE_ESCOLAR, ALIMENTACION_PAE, INCIDENTE_DESACATO, DERECHO_PETICION, DEBIDO_PROCESO, …)\n"
            f"- categoria_tematica ∈ {{{', '.join(CATEGORIA_TEMATICA_VOCAB)}}}\n"
            f"- sentido_fallo_1st ∈ {{{', '.join(SENTIDO_FALLO_VOCAB)}}}\n"
            f"- sentido_fallo_2nd ∈ {{{', '.join(SENTIDO_FALLO_2DA_VOCAB)}}}\n"
            f"- quien_impugno ∈ {{{', '.join(QUIEN_IMPUGNO_VOCAB)}}}\n"
            f"- decision_incidente ∈ {{{', '.join(DECISION_INCIDENTE_VOCAB)}}}\n"
            f"- estado ∈ {{ACTIVO, INACTIVO}} · impugnacion/incidente ∈ {{SI, NO}}"
        )
    except Exception:
        return ""


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
    r"\bcu[aá]nt[ao]s?\s+(?:casos?|tutelas?|expedientes?)\s+(?:hay|tenemos|existen|son)\b(?!\s+en\b)",
], description="Resumen general del cuadro de tutelas")
def _overview(db: Session, msg: str) -> ChatResponse:
    total = _total_cuadro(db)
    _c = lambda *f: db.query(Case).filter(*_real_filter(), *f).count()  # noqa: E731
    activos = _c(Case.estado == "ACTIVO")
    inactivos = _c(Case.estado == "INACTIVO")
    con_fallo1 = _c(Case.sentido_fallo_1st.isnot(None), Case.sentido_fallo_1st != "")
    concede = _c(Case.sentido_fallo_1st.ilike("CONCEDE%"))
    con_impug = _c(Case.impugnacion == "SI")
    con_inc = _c(Case.incidente == "SI")
    by_status = dict(db.query(Case.processing_status, func.count(Case.id)).group_by(Case.processing_status).all())
    by_origen = dict(db.query(Case.origen, func.count(Case.id)).group_by(Case.origen).all())
    answer = (
        f"📊 **Cuadro de tutelas — {total} casos**\n\n"
        f"  • Estado: {activos} ACTIVO · {inactivos} INACTIVO\n"
        f"  • Con fallo de 1ra instancia: {con_fallo1} (de ellos {concede} CONCEDE)\n"
        f"  • Con impugnación: {con_impug}\n"
        f"  • Con incidente de desacato: {con_inc}\n\n"
        f"**Por estado de procesamiento:**\n"
        + "\n".join(f"  • {k}: {v}" for k, v in sorted(by_status.items(), key=lambda x: -x[1]))
        + f"\n\n**Por origen:**\n"
        + "\n".join(f"  • {k or 'sin clasificar'}: {v}" for k, v in sorted(by_origen.items(), key=lambda x: -x[1]))
        + "\n\nPide \"qué columnas tiene el cuadro\" para ver los 18 campos extraídos, "
        "o \"completitud del cuadro\" para ver cuántos casos tienen cada campo lleno."
    )
    return ChatResponse(intent="overview", answer=answer, data={
        "total": total, "activos": activos, "inactivos": inactivos,
        "con_fallo_1ra": con_fallo1, "concede": concede,
        "con_impugnacion": con_impug, "con_incidente": con_inc,
        "by_status": by_status, "by_origen": by_origen,
    }, template_used="overview", confidence=0.95)


# ─── Helpers del cuadro ──────────────────────────────────────────────

def _real_filter():
    """Filtro para excluir los cases shell sin radicado."""
    return (Case.folder_name != "__SIN_RADICADO__",)


def _total_cuadro(db: Session) -> int:
    return db.query(Case).filter(*_real_filter()).count()


@intent("cuadro_columnas", [
    r"\bqu[eé]\s+(?:columnas?|campos?|datos?|informaci[oó]n)\s+(?:tiene|hay\s+en|trae|extrae|contiene)\b.*\bcuadro\b",
    r"\b(?:columnas?|campos?|estructura)\s+del?\s+cuadro\b",
    r"\bqu[eé]\s+(?:se\s+)?extrae\b",
], description="Qué columnas/campos tiene el cuadro de tutelas")
def _cuadro_columnas(db: Session, msg: str) -> ChatResponse:
    from backend.v9.types import EXCEL_FIELDS
    lines = []
    n = 0
    for f in EXCEL_FIELDS:
        if f in ("incidente_2", "fecha_apertura_incidente_2", "responsable_desacato_2", "decision_incidente_2",
                 "incidente_3", "fecha_apertura_incidente_3", "responsable_desacato_3", "decision_incidente_3"):
            continue  # los _2 / _3 ya se mencionan junto al 1º
        n += 1
        desc = _FIELD_DESCRIPTIONS.get(f, "")
        lines.append(f"  {n:>2}. **{f}** — {desc}" if desc else f"  {n:>2}. **{f}**")
    answer = (
        "🗂️ **Columnas del cuadro de tutelas** (lo que extrae v9 a cada expediente):\n\n"
        + "\n".join(lines)
        + "\n\nLos incidentes 2º y 3º replican `incidente · fecha_apertura_incidente · responsable_desacato · decision_incidente`."
    )
    return ChatResponse(intent="cuadro_columnas", answer=answer,
                        data={"fields": list(EXCEL_FIELDS)},
                        template_used="cuadro_columnas", confidence=0.95)


@intent("cuadro_completitud", [
    r"\b(?:completitud|qu[eé]\s+tan\s+completo|cu[aá]nto\s+falta|cobertura)\b.*\bcuadro\b",
    r"\bcuadro\b.*\b(?:completitud|completo|lleno|cobertura)\b",
    r"\bcu[aá]ntos?\s+casos?\s+tienen?\s+(?:cada\s+)?campo\b",
], description="Completitud del cuadro: cuántos casos tienen cada campo lleno")
def _cuadro_completitud(db: Session, msg: str) -> ChatResponse:
    total = _total_cuadro(db)
    key_fields = [
        "radicado_23_digitos", "radicado_forest", "accionante", "accionados",
        "derecho_vulnerado", "categoria_tematica", "juzgado", "ciudad",
        "fecha_ingreso", "asunto", "pretensiones", "oficina_responsable",
        "abogado_responsable", "sentido_fallo_1st", "fecha_fallo_1st",
        "juzgado_2nd", "fecha_respuesta",
    ]
    rows = []
    for f in key_fields:
        col = getattr(Case, f)
        n = db.query(Case).filter(*_real_filter(), col.isnot(None), col != "",
                                  col != "SIN_DETERMINAR").count()
        pct = round(100 * n / total) if total else 0
        rows.append((f, n, pct))
    n_si = lambda f: db.query(Case).filter(*_real_filter(), getattr(Case, f) == "SI").count()  # noqa: E731
    body = "\n".join(f"  • {f:<22} {n:>3}/{total}  ({pct}%)" for f, n, pct in rows)
    answer = (
        f"📈 **Completitud del cuadro** ({total} casos):\n\n{body}\n\n"
        f"  • impugnacion=SI: {n_si('impugnacion')}  ·  incidente=SI: {n_si('incidente')}\n\n"
        "Los campos en blanco no son fallos de extracción: suelen ser expedientes que "
        "solo conservan documentos de 2da instancia, o etapas procesales que aún no ocurren."
    )
    return ChatResponse(intent="cuadro_completitud", answer=answer,
                        data={"total": total, "fields": [{"campo": f, "n": n, "pct": p} for f, n, p in rows]},
                        template_used="cuadro_completitud", confidence=0.92)


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
    # P19: autoridad = campos curados (incidente/decision_incidente/estado).
    # La columna estado_incidente quedó congelada del motor v6 — sus filas
    # stale hacían que el fallback (n==0) nunca disparara y el chat
    # respondiera cifras viejas.
    dec_cols = (Case.decision_incidente, Case.decision_incidente_2, Case.decision_incidente_3)
    if target == "EN_SANCION":
        q = db.query(Case).filter(Case.estado == "ACTIVO",
                                  or_(*[c == "SANCIONA" for c in dec_cols]))
    elif target == "ACTIVO":  # incidente abierto sin decidir
        q = db.query(Case).filter(Case.estado == "ACTIVO", Case.incidente == "SI",
                                  or_(*[or_(c == "EN_TRAMITE", c.is_(None), c == "") for c in dec_cols]))
    elif target == "CUMPLIDO":  # incidente terminado con el caso resuelto
        q = db.query(Case).filter(Case.estado == "INACTIVO", Case.incidente == "SI")
    else:  # EN_CONSULTA: solo existe en la columna legacy curada a mano
        q = db.query(Case).filter(Case.estado_incidente == target)
    n = q.count()
    samples = q.with_entities(Case.id, Case.folder_name).limit(5).all()
    sample_str = "\n".join(f"  • #{cid}: {fn}" for cid, fn in samples) or "  (ninguno)"
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
        # Intent bien clasificado por regex; "sin datos" es una respuesta válida, no baja
        # la confianza de la clasificación (antes 0.5 → fallaba el test de routing cuando la
        # DB no tenía accionados poblados).
        return ChatResponse(intent="top_accionados", answer="Sin datos.",
                            template_used="top_accionados", confidence=0.85)
    body = "\n".join(f"  {i+1:>2}. {(a or '')[:65]:<65} — {n}" for i, (a, n) in enumerate(rows))
    return ChatResponse(intent="top_accionados", answer=f"🏢 **Top accionados**:\n\n{body}",
                        data={"top": [{"accionado": a, "count": n} for a, n in rows]},
                        template_used="top_accionados", confidence=0.85)


@intent("list_en_sancion", [
    r"\b(?:lista|listar|mu[eé]strame|cu[aá]les)\s+.*\bsanci[oó]n\b",
    r"\bcasos?\s+(?:en\s+)?sanci[oó]n\s+(?:lista|completa|todos?)\b",
], description="Listado completo de casos en sanción")
def _list_en_sancion(db: Session, msg: str) -> ChatResponse:
    dec_cols = (Case.decision_incidente, Case.decision_incidente_2, Case.decision_incidente_3)
    cases = db.query(Case.id, Case.folder_name, Case.accionante, Case.juzgado).filter(
        *_real_filter(),
        or_(Case.estado_incidente == "EN_SANCION", *[c == "SANCIONA" for c in dec_cols]),
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
    rows = db.query(Case.abogado_responsable, func.count(Case.id)).filter(
        *_real_filter()
    ).group_by(Case.abogado_responsable).order_by(func.count(Case.id).desc()).all()
    body = "\n".join(
        f"  • {(a or 'SIN ASIGNAR'):40s}  {n} casos"
        for a, n in rows
    )
    return ChatResponse(intent="count_by_abogado",
                        answer=f"👥 **Casos por abogado responsable**:\n\n{body}",
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
        "villamizar": "MARIA CRISTINA VILLAMIZAR SCHILLER",
        "schiller": "MARIA CRISTINA VILLAMIZAR SCHILLER",
        "diego otilio": "DIEGO OTILIO RODRIGUEZ NUÑEZ",
        "jorge": "JORGE JAVIER SEPULVEDA JAIMES",
        "bohorquez": "JHON ALEXANDER BOHORQUEZ CAMARGO",
        "bohórquez": "JHON ALEXANDER BOHORQUEZ CAMARGO",
        "cruz lizcano": "JUAN DIEGO CRUZ LIZCANO",
        "lizcano": "JUAN DIEGO CRUZ LIZCANO",
        "barroso": "ANGELICA YADIRA BARROSO SARMIENTO",
        "colmenares": "VICTOR ALFONSO COLMENARES NIÑO",
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

    # Matchea por apellido(s) del nombre canónico contra `abogado_responsable` (que viene
    # del roster del Grupo Jurídico, p.ej. "M.C. Villamizar Schiller", "Bohórquez").
    surname = target.split()[-1]
    cases = db.query(Case).filter(
        *_real_filter(),
        or_(Case.abogado_responsable.ilike(f"%{surname}%"), Case.abogado_responsable == target),
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
            *_real_filter(),
            or_(Case.oficina_responsable == target, Case.oficina_responsable.ilike(f"%{target}%")),
        )
        total = q.count()
        cases = q.limit(20).all()
        body = "\n".join(
            f"  • #{c.id} {(c.folder_name or '')[:55]} | "
            f"{(c.abogado_responsable or '-')}"
            for c in cases
        )
        more = f"\n\n  ... y {total - 20} más (total {total})" if total > 20 else ""
        return ChatResponse(intent="count_by_dependencia",
                            answer=f"🏢 **{total} casos en {target}**:\n\n{body}{more}",
                            data={"dependencia": target, "count": total},
                            template_used="count_by_dependencia", confidence=0.9)
    # Sin filtro: distribución total
    rows = db.query(Case.oficina_responsable, func.count(Case.id)).filter(
        *_real_filter()
    ).group_by(Case.oficina_responsable).order_by(func.count(Case.id).desc()).all()
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
    cases = db.query(Case).filter(*_real_filter()).all()
    now = utcnow()
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
        *_real_filter(),
        Case.sentido_fallo_1st.isnot(None),
        Case.sentido_fallo_1st != "",
    ).group_by(Case.sentido_fallo_1st).order_by(func.count(Case.id).desc()).all()

    if target:
        q = db.query(Case).filter(
            *_real_filter(),
            Case.sentido_fallo_1st.ilike(f"%{target}%"),
        )
        total = q.count()
        cases = q.limit(15).all()
        body = "\n".join(
            f"  • #{c.id} {(c.folder_name or '')[:55]} | "
            f"{(c.abogado_responsable or '-')}"
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
    now = utcnow()
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
        *_real_filter(),
        Case.categoria_tematica.isnot(None),
        Case.categoria_tematica != "",
        Case.categoria_tematica != "SIN_DETERMINAR",
    ).group_by(Case.categoria_tematica).order_by(func.count(Case.id).desc()).limit(20).all()
    # también la distribución por `asunto` (más fino)
    asu = db.query(Case.asunto, func.count(Case.id)).filter(
        *_real_filter(), Case.asunto.isnot(None), Case.asunto != "", Case.asunto != "SIN_DETERMINAR",
    ).group_by(Case.asunto).order_by(func.count(Case.id).desc()).limit(12).all()
    if not rows and not asu:
        return ChatResponse(intent="temas_top",
                            answer="No hay datos de categoría temática.",
                            template_used="temas_top", confidence=0.4)
    body = "\n".join(f"  • {(t or '?'):26s}  {n}" for t, n in rows)
    body_asu = "\n".join(f"  • {(t or '?'):26s}  {n}" for t, n in asu)
    return ChatResponse(intent="temas_top",
                        answer=f"🏷️ **Categorías temáticas (grupo L2):**\n\n{body}\n\n**Por asunto (acción concreta):**\n\n{body_asu}",
                        data={"categorias": [{"tema": t, "count": n} for t, n in rows],
                              "asuntos": [{"asunto": t, "count": n} for t, n in asu]},
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
                            "📊 **El cuadro de tutelas**\n"
                            "  • cuántas tutelas hay / resumen / panorama\n"
                            "  • qué columnas tiene el cuadro\n"
                            "  • completitud del cuadro\n\n"
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


# ─── Tier 2: LLM fallback (opcional — gated por LLM_LOCAL_PRIMARY=true) ───────────
#
# El LLM local (Qwen3-4B en :8765) NUNCA toca SQL. Se usa para dos cosas:
#   1) ROUTER — mapear una pregunta libre a una de las plantillas Tier-1.
#   2) FREEFORM — si ninguna plantilla aplica, responder de forma orientativa
#      (conceptual/jurídica) con el contexto del cuadro, sin acceso a datos.
# Si el modelo no está disponible o tarda, se degrada limpio (vuelve a Tier-1).

def _llm_available() -> bool:
    if not LLM_ENABLED:
        return False
    try:  # lazy restart si llama-server está pausado tras una extracción
        from backend.services.llm_mutex import ensure_llm_up, PAUSE_FLAG
        if PAUSE_FLAG.exists():
            logger.info("LLM pausado — relanzando lazy")
            return ensure_llm_up(wait_s=30)
    except Exception as e:
        logger.debug("ensure_llm_up falló: %s", e)
    return True


def _llm_chat(messages: list[dict], *, max_tokens: int = 200, temperature: float = 0.1, timeout: float = 12.0) -> Optional[str]:
    try:
        r = requests.post(
            f"{LLM_URL}/v1/chat/completions",
            json={"model": LLM_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": temperature},
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.debug("LLM call failed: %s", str(e)[:120])
        return None


def _intent_catalog_text() -> str:
    return "\n".join(f"  - {it['name']}: {it['desc']}" for it in INTENTS if it["desc"])


def _llm_intent_fallback(message: str) -> Optional[dict]:
    """Pide al LLM que mapee la pregunta a una plantilla Tier-1. Devuelve {"template": ...} o None."""
    if not _llm_available():
        return None
    prompt = (
        "Eres un router de intención para un asistente jurídico de tutelas. Estas son las "
        "plantillas disponibles (nombre: para qué sirve):\n"
        f"{_intent_catalog_text()}\n\n"
        f'Pregunta del usuario: "{message}"\n'
        'Responde SOLO con JSON: {"template": "<nombre exacto de una plantilla>"} si alguna '
        'aplica, o {"template": null} si ninguna aplica claramente. Nada más.'
    )
    text = _llm_chat([{"role": "user", "content": prompt}], max_tokens=64, temperature=0.0, timeout=10.0)
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            import json
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def _llm_freeform(message: str, db: Session) -> Optional[ChatResponse]:
    """Respuesta orientativa del LLM cuando ninguna plantilla aplica. Sin acceso a datos:
    el LLM responde con el contexto del cuadro + el marco normativo, y si la pregunta
    necesita datos concretos, sugiere usar una de las plantillas."""
    if not _llm_available():
        return None
    try:
        n_cases = _total_cuadro(db)
    except Exception:
        n_cases = None
    from backend.v9.types import EXCEL_FIELDS
    cuadro_fields = ", ".join(f for f in EXCEL_FIELDS)
    system = (
        "Eres el asistente jurídico de la oficina de tutelas de la Secretaría de Educación de la "
        "Gobernación de Santander. Respondes en español, conciso, profesional, dirigido a abogados "
        "y jefes de oficina. NO inventes cifras: si no las sabes, dilo y sugiere preguntar con una "
        "consulta concreta. NO des asesoría que comprometa a la entidad; eres orientativo.\n\n"
        f"Estado actual del cuadro de tutelas: {('≈' + str(n_cases) + ' casos') if n_cases else 'varios casos'} "
        f"en la base. El cuadro tiene estas columnas extraídas automáticamente: {cuadro_fields}.\n"
        f"{_cuadro_vocab_lines()}\n\n"
        f"{_LEGAL_CONTEXT}\n\n"
        "Si la pregunta pide un dato concreto del cuadro (conteos, listados, un caso por número, "
        "carga por abogado/dependencia, alertas, plazos, distribución de fallos, top temas, casos "
        "por municipio…), NO lo inventes: indica brevemente que esa consulta se hace pidiéndola "
        "directamente (por ejemplo: 'resumen', 'caso 142', 'casos en sanción', 'casos por abogado', "
        "'tutelas en Bucaramanga', 'completitud del cuadro', 'qué columnas tiene el cuadro')."
    )
    text = _llm_chat(
        [{"role": "system", "content": system}, {"role": "user", "content": message}],
        max_tokens=480, temperature=0.2, timeout=20.0,
    )
    if not text or not text.strip():
        return None
    return ChatResponse(intent="llm_freeform", answer=text.strip(),
                        template_used="llm_freeform", confidence=0.6, llm_used=True)


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

    # Tier 2a: LLM router → mapear a una plantilla Tier-1
    llm_result = _llm_intent_fallback(msg)
    if llm_result and llm_result.get("template"):
        for it in INTENTS:
            if it["name"] == llm_result["template"]:
                logger.info("chat LLM-routed intent=%s", it["name"])
                resp = it["fn"](db, msg)
                if resp.confidence >= 0.5:
                    resp.llm_used = True
                    return resp

    # Si hubo match parcial low-conf, retornarlo (mejor que nada)
    if best_low_conf is not None:
        return best_low_conf

    # Tier 2b: respuesta libre orientativa del LLM (si está disponible)
    free = _llm_freeform(msg, db)
    if free is not None:
        logger.info("chat LLM-freeform answer")
        return free

    # Sin match — ofrecer ejemplos útiles
    return ChatResponse(
        intent="unknown",
        answer=(
            "No identifiqué bien la pregunta. Prueba con algo como:\n\n"
            "  • \"resumen\" / \"cuántas tutelas hay\"\n"
            "  • \"qué columnas tiene el cuadro\" · \"completitud del cuadro\"\n"
            "  • \"caso 142\" · \"buscar accionante NOMBRE\" · \"tutelas en Bucaramanga\"\n"
            "  • \"casos en sanción\" · \"plazos por vencer\" · \"cuántos rojos\"\n"
            "  • \"casos por abogado\" · \"carga de Juan Diego\" · \"casos de talento humano\"\n"
            "  • \"distribución de fallos\" · \"cuántos fallos concede\" · \"top temas\"\n\n"
            "Escribe \"ayuda\" para ver todo lo que puedo responder."
        ),
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
