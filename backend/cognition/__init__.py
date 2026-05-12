"""Paquete `cognition`.

⚠️ ESTADO (Modernización Fase 7): de este paquete, lo que sigue VIVO es
`legal_schema.py` (mapa judicial Santander + `SED_TEMA_MAPPING` +
`categoria_tematica_de_asunto`, lo usa v9), `bayesian_assignment.py` (lo usa
`extraction/doc_ops._verify_bayesian`), `confidence.py` y `folder_renamer.py`.

Todo lo demás es el **pipeline cognitivo v8 (LEGACY)** — sin uso desde v9; su único
importador es el ya-en-cuarentena `backend/_legacy/extraction/unified_cognitive.py`.
Cada archivo legacy está marcado `# LEGACY v8` en la primera línea. Se borra en bloque
en la Fase 8 (junto con `backend/_legacy/extraction/unified_cognitive.py`):
    cognitive_complementary_ai, cognitive_fill, focused_field_extractors, entropy,
    case_classifier, canonical_identifiers, procedural_timeline, ner_spacy,
    cie10_to_derecho, decision_extractor, document_authority, entity_extractor,
    flag_normalizer, narrative_builder, semantic_matcher, timeline_builder,
    zone_classifier, cognitive_persist, live_consolidator,
    agent/{lifecycle, orchestrator, semantic_enricher, tools}.

Por ahora se conservan los re-exports de abajo para no romper a ese consumidor legacy.

Pipeline cognitivo v8 (histórico):
    zone_classifier → entity_extractor → cie10_to_derecho → timeline_builder
    → decision_extractor → narrative_builder → cognitive_fill
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
