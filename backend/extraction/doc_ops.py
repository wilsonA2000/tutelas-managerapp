"""Utilidades de documentos del pipeline — fachada estable.

(Modernización Fase 7, substep 7.1) Estas son las funciones de
`backend/extraction/pipeline.py` que el código vivo usa de verdad — lectura de texto,
clasificación de doctype, verificación de pertenencia doc↔case, dedup, re-extracción.
NO incluye `process_folder` ni el resto del motor de extracción v8 (eso se reemplaza
por `backend/v9/pipeline.py` en el substep 7.3).

Por ahora esto re-exporta desde `pipeline.py`; cuando el motor v8 se retire (substep 7.5),
los cuerpos de estas funciones se mueven aquí y `pipeline.py` desaparece. Los importadores
deben depender de ESTE módulo (`backend.extraction.doc_ops`), no de `pipeline`.
"""

from __future__ import annotations

from backend.extraction.pipeline import (
    extract_document_text,
    classify_doc_type,
    reextract_document,
    compute_file_hash,
    detect_duplicate_documents,
    verify_document_belongs,
    verify_all_documents,
    _verify_bayesian,   # `services/cleanup_actions.py` lo importa directo (reverify sospechosos)
)

__all__ = [
    "extract_document_text",
    "classify_doc_type",
    "reextract_document",
    "compute_file_hash",
    "detect_duplicate_documents",
    "verify_document_belongs",
    "verify_all_documents",
    "_verify_bayesian",
]
