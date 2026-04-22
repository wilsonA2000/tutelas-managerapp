"""Módulo cognitivo (v5.3.1) — emula razonamiento jurídico sin IA externa.

Codifica el "mapa mental" que un LLM aplica implícitamente al leer una
tutela, pero con lógica determinística y auditable. Objetivo: reducir la
dependencia de IA externa del ~20% (v5.2) a <5% (v5.3.1), dejando el LLM
solo para casos verdaderamente ambiguos.

Pipeline cognitivo:
    1. zone_classifier   — secciones del documento (encabezado, hechos, resuelve...)
    2. entity_extractor  — actores con roles (accionante/accionado/vinculado/juez)
    3. coreference       — resuelve "la accionante" → nombre real
    4. cie10_to_derecho  — diagnóstico → derechos fundamentales implícitos
    5. timeline_builder  — cronología de hechos desde múltiples documentos
    6. decision_extractor— sentido_fallo + fecha + razón
    7. narrative_builder — OBSERVACIONES / ASUNTO / PRETENSIONES por plantilla
"""

from backend.cognition.zone_classifier import classify_zones, DocZones
from backend.cognition.entity_extractor import extract_actors, ActorSet
from backend.cognition.cie10_to_derecho import infer_derechos_from_dx
from backend.cognition.decision_extractor import extract_decision, Decision
from backend.cognition.narrative_builder import (
    build_asunto, build_pretensiones, build_observaciones, build_derecho_vulnerado,
)
from backend.cognition.cognitive_fill import cognitive_fill, SEMANTIC_FIELDS_COGNITIVE

__all__ = [
    "classify_zones", "DocZones",
    "extract_actors", "ActorSet",
    "infer_derechos_from_dx",
    "extract_decision", "Decision",
    "build_asunto", "build_pretensiones", "build_observaciones", "build_derecho_vulnerado",
    "cognitive_fill", "SEMANTIC_FIELDS_COGNITIVE",
]
