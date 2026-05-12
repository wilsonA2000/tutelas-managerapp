"""Paquete `cognition`.

Estado tras la modernización (Fase 7-8). Lo que sigue VIVO:
- `legal_schema.py` — mapa judicial Santander + `SED_TEMA_MAPPING` +
  `categoria_tematica_de_asunto`. Lo usa el pipeline v9 (`backend/v9/field_extractor.py`,
  `backend/routers/chat.py`).
- `bayesian_assignment.py` + `canonical_identifiers.py` — los usa
  `extraction/doc_ops._verify_bayesian` (verificación de pertenencia doc↔caso).
- `confidence.py`, `folder_renamer.py` — utilidades vivas.
- El "fill cognitivo determinista" (`cognitive_fill` → `zone_classifier`,
  `entity_extractor`, `decision_extractor`, `narrative_builder`, `cie10_to_derecho`,
  `semantic_matcher`, `timeline_builder`, `ner_spacy`) — lo usa el scheduler de active
  learning (`services/active_learning_scheduler.py`, cron 3 AM) y `ner_spacy._get_nlp`
  lo cargan `main.py` y `routers/extraction.py`. (Pendiente de futura revisión: si se
  retira ese scheduler, esta sub-rama queda muerta.)

Borrado en la Fase 8 (era solo del motor v8 / RunPod): `cognitive_complementary_ai`,
`focused_field_extractors`, `document_authority`, `cognitive_persist`, `live_consolidator`,
`entropy`, `procedural_timeline`, `case_classifier`, `flag_normalizer`,
`agent/{lifecycle,orchestrator,semantic_enricher,tools}` — junto con
`backend/_legacy/extraction/{pipeline,unified,unified_cognitive}.py`.
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
