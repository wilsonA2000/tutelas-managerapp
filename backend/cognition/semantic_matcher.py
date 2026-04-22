"""Semantic matcher con spaCy word vectors (es_core_news_lg).

Reemplaza sentence-transformers (que requiere PyTorch, ~2GB).
spaCy `lg` ya incluye word vectors de 300 dims. `doc.similarity()` es
cosine similarity entre vectores promediados — suficiente para:

- Detectar pretensiones por significado ("solicito traslado" ≈ "pido reubicación").
- Agrupar casos similares.
- Identificar intent cuando patrones regex fallan.

Corre en CPU, sin dependencias adicionales.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Iterable

_logger = logging.getLogger("tutelas.cognition.semantic")


# Plantillas de pretensiones comunes — se comparan por similarity con el texto del caso.
# Si similarity > umbral, se considera match aunque las palabras exactas difieran.
PRETENSION_TEMPLATES: dict[str, str] = {
    "traslado_docente": "solicito el traslado del docente por razones de seguridad o conveniencia administrativa",
    "nombramiento_docente": "solicito el nombramiento de un docente para la institución educativa",
    "docente_apoyo": "solicito la asignación de un docente de apoyo pedagógico para estudiantes con discapacidad",
    "reintegro_laboral": "solicito el reintegro al cargo y el pago de salarios dejados de percibir",
    "pago_prestaciones": "solicito el pago de prestaciones sociales cesantías o pensión",
    "tratamiento_medico": "solicito la autorización de tratamiento médico medicamento o cirugía",
    "transporte_escolar": "solicito el transporte escolar gratuito para el menor",
    "alimentacion_escolar": "solicito la inclusión en el programa de alimentación escolar PAE",
    "cupo_matricula": "solicito un cupo o matrícula escolar para el estudiante",
    "respuesta_peticion": "solicito la respuesta de fondo al derecho de petición presentado",
    "proteccion_menor": "solicito la protección de los derechos fundamentales del menor",
    "unidad_familiar": "solicito la protección a la unidad familiar y reunificación",
}


@lru_cache(maxsize=1)
def _nlp():
    """Singleton spaCy lg con disables para velocidad."""
    try:
        from backend.cognition.ner_spacy import _get_nlp
        return _get_nlp()
    except Exception as e:
        _logger.warning("spaCy NLP no disponible: %s", e)
        return None


@lru_cache(maxsize=16)
def _template_doc(template_text: str):
    nlp = _nlp()
    if nlp is None:
        return None
    return nlp(template_text)


def classify_pretension(text: str, threshold: float = 0.65) -> tuple[str, float] | None:
    """Clasifica el texto contra plantillas de pretensiones.

    Retorna (categoría, similarity) si la mejor coincidencia > threshold, else None.
    """
    nlp = _nlp()
    if nlp is None or not text or len(text) < 20:
        return None
    text_sample = text[:5000]  # suficiente para capturar pretensiones narrativas
    doc = nlp(text_sample)
    # Validar que el doc tiene vectores no-cero (si el texto es todo stopwords, vector=0)
    if not doc.has_vector or doc.vector_norm == 0:
        return None
    best = None
    best_score = 0.0
    for label, template in PRETENSION_TEMPLATES.items():
        t_doc = _template_doc(template)
        if t_doc is None or t_doc.vector_norm == 0:
            continue
        try:
            score = doc.similarity(t_doc)
            if score > best_score:
                best_score = score
                best = label
        except Exception:
            continue
    if best and best_score >= threshold:
        return (best, best_score)
    return None


def similar_to(text_a: str, text_b: str) -> float:
    """Similarity score cosine entre dos textos. 0 si NLP no disponible."""
    nlp = _nlp()
    if nlp is None or not text_a or not text_b:
        return 0.0
    try:
        a = nlp(text_a[:3000])
        b = nlp(text_b[:3000])
        if a.vector_norm == 0 or b.vector_norm == 0:
            return 0.0
        return float(a.similarity(b))
    except Exception:
        return 0.0


def group_by_similarity(texts: list[str], threshold: float = 0.8) -> list[list[int]]:
    """Agrupa índices de textos por similaridad > threshold.

    Simple clustering: linkage por umbral, no optimizado para grandes N.
    """
    n = len(texts)
    if n < 2:
        return [[i] for i in range(n)]
    nlp = _nlp()
    if nlp is None:
        return [[i] for i in range(n)]

    docs = [nlp(t[:2000]) for t in texts]
    groups = []
    assigned = set()
    for i in range(n):
        if i in assigned:
            continue
        group = [i]
        assigned.add(i)
        for j in range(i + 1, n):
            if j in assigned:
                continue
            if docs[i].vector_norm == 0 or docs[j].vector_norm == 0:
                continue
            if docs[i].similarity(docs[j]) >= threshold:
                group.append(j)
                assigned.add(j)
        groups.append(group)
    return groups
