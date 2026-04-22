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
from dataclasses import dataclass
from typing import Any

from backend.agent.extractors.base import ExtractionResult
from backend.cognition.zone_classifier import classify_zones
from backend.cognition.entity_extractor import extract_actors
from backend.cognition.decision_extractor import extract_decision
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

    # Accionante
    if actors.accionantes:
        _maybe_set("accionante", actors.accionantes[0].name, 75, "cognition/actor_extractor")

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
