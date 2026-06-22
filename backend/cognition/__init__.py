"""Paquete `cognition` — utilidades cognitivas vivas que usa el pipeline v9.

Tras la de-sobreingeniería (Fase 3, 2026-06-21) solo sobrevive lo que tiene
consumidor real (importado directamente por su submódulo, sin re-exports aquí):

- `legal_schema.py` — mapa judicial Santander + `SED_TEMA_MAPPING` +
  `categoria_tematica_de_asunto`. Lo usa v9 (`field_extractor_pass`, `llm_gap_fill`,
  `regex_pass`) y `routers/chat.py`.
- `bayesian_assignment.py` + `canonical_identifiers.py` — verificación de pertenencia
  documento↔caso (`extraction/doc_ops.verify_document_belongs`, gated por
  `USE_COGNITIVE_PIPELINE`).
- `folder_renamer.py` — normalización de homoglyphs + renombrado de carpetas (v9 + email).

Retirado en Fase 3 (cron `active_learning` nunca produjo output consumido — 0 filas
ACTIVE_LEARNING): `cognitive_fill`, `zone_classifier`, `entity_extractor`,
`decision_extractor`, `narrative_builder`, `semantic_matcher`, `timeline_builder`,
`cie10_to_derecho`, `ner_spacy`, `confidence`, `services/active_learning_scheduler`,
`agent/extractors/base`. (Viven solo en el historial de git.)
"""
