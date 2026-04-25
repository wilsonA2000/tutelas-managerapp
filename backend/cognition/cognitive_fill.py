"""Cognitive fill: intenta rellenar los ~8 campos semánticos SIN IA externa.

Ejecuta el pipeline cognitivo (zones → actors → cie10 → decision → narrative)
y produce un dict `cognitive_results` con los campos que logró llenar con
razonable confianza. Los que queden vacíos/bajos son los que realmente
necesitan IA externa.

Uso típico en unified.py:
    cog = cognitive_fill(case, all_text, existing_regex_results)
    # fusionar en regex_results antes de decidir si llamar IA
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from backend.agent.extractors.base import ExtractionResult
from backend.cognition.zone_classifier import classify_zones
from backend.cognition.entity_extractor import extract_actors
from backend.cognition.decision_extractor import extract_decision
from backend.cognition.folder_renamer import clean_accionante, is_likely_real_name
from backend.cognition.narrative_builder import (
    build_asunto, build_pretensiones, build_observaciones, build_derecho_vulnerado,
)

_logger = logging.getLogger("tutelas.cognition")


SEMANTIC_FIELDS_COGNITIVE = {
    "accionante", "accionados", "vinculados",
    "derecho_vulnerado", "asunto", "pretensiones",
    "observaciones", "sentido_fallo_1st", "fecha_fallo_1st",
    "sentido_fallo_2nd", "fecha_fallo_2nd",
    "impugnacion", "quien_impugno",
}


def _to_result(value: str, confidence: int, source: str) -> ExtractionResult:
    return ExtractionResult(
        value=value,
        confidence=confidence,
        source=source,
        method="cognition",
        reasoning=f"Cognición local ({source})",
    )


def _accionante_collides_with_juzgado(name: str, juzgado: str) -> bool:
    """True si el 'accionante' candidato es en realidad un juzgado."""
    if not name:
        return False
    n = name.upper().strip()
    # Palabras-tipo institución judicial en el nombre (siempre rechazo)
    if "JUZGADO" in n or "TRIBUNAL" in n or "CORTE" in n or "MAGISTRADO" in n:
        return True
    # Solapamiento substancial con el campo juzgado ya conocido
    j = (juzgado or "").upper().strip()
    if len(j) >= 10 and (j in n or n in j):
        return True
    return False


# Patrones explícitos que preceden al accionante en encabezados de fallos/tutelas
# Capturan hasta 6 palabras tipo nombre (mayúsculas/tildes/ñ).
_ACCIONANTE_HEADER_RE = re.compile(
    r"\b(?:Accionante|Demandante|Tutelante|Actor)\s*[:\-]?\s*"
    r"((?:[A-ZÁÉÍÓÚÑ][\w\u00C0-\u017F'’.\-]+\s+){1,5}"
    r"[A-ZÁÉÍÓÚÑ][\w\u00C0-\u017F'’.\-]+)",
    re.UNICODE,
)


def _pick_accionante_from_text(full_text: str, juzgado: str = "") -> str:
    """Fallback FIX 6: extraer accionante cuando actor_extractor falla.

    Estrategia (en orden):
    1. Regex sobre patrones explícitos "Accionante:|Demandante:|Tutelante:|Actor:"
       (más confiable que NER porque captura nombre completo).
    2. spaCy PERSON ranked por aparición temprana + frecuencia.

    Descartando juzgados/tribunales en ambas fases.
    """
    head = full_text[:16000]

    # Paso 1: regex header explícito
    for m in _ACCIONANTE_HEADER_RE.finditer(head):
        candidate = clean_accionante(m.group(1))
        if not candidate or not is_likely_real_name(candidate):
            continue
        if _accionante_collides_with_juzgado(candidate, juzgado):
            continue
        return candidate

    # Paso 2: NER fallback
    try:
        from backend.cognition.ner_spacy import extract_persons
    except Exception:
        return ""
    persons = extract_persons(head, min_length=8)
    if not persons:
        return ""
    seen: dict[str, dict] = {}
    for p in persons:
        candidate = clean_accionante(p.text)
        if not candidate or not is_likely_real_name(candidate):
            continue
        if _accionante_collides_with_juzgado(candidate, juzgado):
            continue
        rec = seen.setdefault(candidate, {"count": 0, "first_pos": p.start})
        rec["count"] += 1
        rec["first_pos"] = min(rec["first_pos"], p.start)

    if not seen:
        return ""
    ranked = sorted(seen.items(), key=lambda it: (-it[1]["count"], it[1]["first_pos"] * 2))
    return ranked[0][0]


# alias para compat con tests existentes
_pick_accionante_from_ner = _pick_accionante_from_text


def cognitive_fill(
    case_meta: dict[str, Any],
    full_text: str,
    existing: dict[str, ExtractionResult] | None = None,
    documents: list[dict] | None = None,
) -> dict[str, ExtractionResult]:
    """Aplica el pipeline cognitivo al texto completo del caso.

    Args:
        case_meta: dict con fields ya extraídos por regex/DB
                   (fecha_ingreso, radicado_23_digitos, radicado_forest,
                    abogado_responsable, incidente, etc.)
        full_text: concatenación de textos de documentos del caso.
        existing: resultados regex previos (para no sobrescribir si
                  confianza > 80).

    Returns:
        dict campo_lowercase → ExtractionResult (solo los que llenó).
    """
    if not full_text:
        return {}
    existing = existing or {}

    zones = classify_zones(full_text)
    actors = extract_actors(full_text, zones)
    decision = extract_decision(full_text, zones)

    out: dict[str, ExtractionResult] = {}

    def _maybe_set(field: str, value: str, confidence: int, source: str):
        if not value:
            return
        # Respetar regex con alta confianza
        prev = existing.get(field)
        if prev and prev.confidence >= 80:
            return
        out[field] = _to_result(value, confidence, source)

    # Accionante (FIX 6 — validación + fallback NER):
    # 1. Tomar el del actor_extractor, sanitizar con clean_accionante,
    #    descartar si parece juzgado o no es nombre real.
    # 2. Si falla, usar spaCy NER PERSON ranked por posición/frecuencia.
    juzgado_known = case_meta.get("juzgado", "")
    accionante_candidate = ""
    if actors.accionantes:
        raw = actors.accionantes[0].name
        cleaned = clean_accionante(raw)
        if (cleaned and is_likely_real_name(cleaned)
                and not _accionante_collides_with_juzgado(cleaned, juzgado_known)):
            accionante_candidate = cleaned

    if not accionante_candidate:
        text_pick = _pick_accionante_from_text(full_text, juzgado_known)
        if text_pick:
            accionante_candidate = text_pick
            _logger.info("cognitive_fill case=%s accionante via text fallback: %r",
                         case_meta.get("id"), text_pick)

    if accionante_candidate:
        _maybe_set("accionante", accionante_candidate, 75,
                   "cognition/actor_extractor" if (actors.accionantes and accionante_candidate == clean_accionante(actors.accionantes[0].name))
                   else "cognition/text_fallback")

    # Accionados (lista separada por " - ")
    if actors.accionados:
        val = " - ".join(a.name for a in actors.accionados[:5])
        _maybe_set("accionados", val, 70, "cognition/actor_extractor")

    # Vinculados
    if actors.vinculados:
        val = " - ".join(a.name for a in actors.vinculados[:6])
        _maybe_set("vinculados", val, 70, "cognition/actor_extractor")

    # Derechos vulnerados (combinando existing)
    existing_dv = existing.get("derecho_vulnerado")
    prev_dv = existing_dv.value if existing_dv else ""
    dv = build_derecho_vulnerado(full_text, prev_dv)
    if dv:
        _maybe_set("derecho_vulnerado", dv, 78, "cognition/cie10_keyword")

    # Decisión primera instancia
    if decision.sentido:
        _maybe_set("sentido_fallo_1st", decision.sentido, 80, "cognition/decision_extractor")
    if decision.fecha:
        _maybe_set("fecha_fallo_1st", decision.fecha, 80, "cognition/decision_extractor")
    if decision.segunda_instancia:
        _maybe_set("sentido_fallo_2nd", decision.segunda_instancia, 75, "cognition/decision_extractor")
    if decision.fecha_segunda:
        _maybe_set("fecha_fallo_2nd", decision.fecha_segunda, 75, "cognition/decision_extractor")
    if decision.impugnacion:
        _maybe_set("impugnacion", decision.impugnacion, 75, "cognition/decision_extractor")
    if decision.quien_impugno:
        _maybe_set("quien_impugno", decision.quien_impugno, 70, "cognition/decision_extractor")

    # Campos narrativos (asunto / pretensiones / observaciones)
    asunto = build_asunto(actors, dv or prev_dv, full_text)
    pret = build_pretensiones(actors, dv or prev_dv, full_text, asunto)

    _maybe_set("asunto", asunto, 65, "cognition/narrative_builder")
    _maybe_set("pretensiones", pret, 65, "cognition/narrative_builder")

    obs_meta = {
        "fecha_ingreso": case_meta.get("fecha_ingreso", ""),
        "radicado_23_digitos": case_meta.get("radicado_23_digitos", ""),
        "radicado_forest": case_meta.get("radicado_forest", ""),
        "abogado_responsable": case_meta.get("abogado_responsable", ""),
        "incidente": case_meta.get("incidente", ""),
    }
    obs = build_observaciones(actors, dv or prev_dv, decision, obs_meta,
                              events=None, documents=documents)
    _maybe_set("observaciones", obs, 60, "cognition/narrative_builder")

    _logger.info(
        "cognitive_fill case=%s filled=%d fields: %s",
        case_meta.get("id"), len(out), sorted(out.keys()),
    )
    return out
