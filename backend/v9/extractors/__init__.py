"""Paquete `extractors` — descomposición del god-file v9/field_extractor.py por dominio.

De-sobreingeniería F6 (2026-06-21). `_shared.py` aloja los helpers cross-cutting
(usados por varios dominios) para que cada módulo de dominio los importe SIN crear
ciclo con field_extractor.py (que re-exporta todo como facade para no romper los ~25
imports externos de helpers privados en tests/scripts/services).
"""
