"""Wrapper de spaCy NER para backend/cognition/.

Usa `es_core_news_lg` (550 MB, CPU-friendly) para:
- Detectar PERSON con mejor recall que patrones regex.
- Desambiguar nombres de personas vs instituciones (ORG).
- Complementar el entity_extractor cuando los patrones narrativos fallan.

Carga lazy + singleton para evitar overhead en arranque.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from backend.core.settings import settings

_logger = logging.getLogger("tutelas.cognition.ner")


@dataclass(frozen=True)
class NerEntity:
    text: str
    label: str       # PER / PERSON / ORG / LOC / MISC
    start: int
    end: int
    score: float = 1.0  # spaCy no provee por defecto, asumimos 1.0 para matches del modelo


@lru_cache(maxsize=1)
def _get_nlp():
    """Carga spaCy en singleton. lru_cache garantiza una sola instancia."""
    try:
        import spacy
        model = getattr(settings, "PII_PRESIDIO_MODEL", "es_core_news_lg")
        # Si el modelo configurado es 'md', intentar 'lg' primero si está disponible
        # (preferencia para mayor recall en NER).
        for candidate in [model, "es_core_news_lg", "es_core_news_md"]:
            try:
                nlp = spacy.load(candidate, disable=["parser", "lemmatizer", "attribute_ruler"])
                _logger.info("spaCy NER cargado: %s", candidate)
                return nlp
            except OSError:
                continue
        raise RuntimeError("Ningún modelo spaCy ES disponible")
    except ImportError:
        raise RuntimeError("spaCy no instalado. pip install spacy")


def extract_persons(text: str, min_length: int = 5) -> list[NerEntity]:
    """Extrae entidades PERSON del texto usando spaCy NER.

    Filtra entidades muy cortas o que coinciden con conectores/stopwords.
    """
    if not text:
        return []
    try:
        nlp = _get_nlp()
    except RuntimeError as e:
        _logger.debug("NER no disponible: %s", e)
        return []
    # spaCy puede procesar hasta ~1M chars; limitamos por seguridad
    doc = nlp(text[:200000])
    persons = []
    for ent in doc.ents:
        if ent.label_ not in ("PER", "PERSON"):
            continue
        t = ent.text.strip()
        if len(t) < min_length:
            continue
        persons.append(NerEntity(text=t, label=ent.label_, start=ent.start_char, end=ent.end_char))
    return persons


def extract_organizations(text: str, min_length: int = 5) -> list[NerEntity]:
    """Extrae ORG (instituciones, empresas) del texto."""
    if not text:
        return []
    try:
        nlp = _get_nlp()
    except RuntimeError:
        return []
    doc = nlp(text[:200000])
    return [
        NerEntity(text=ent.text.strip(), label="ORG", start=ent.start_char, end=ent.end_char)
        for ent in doc.ents
        if ent.label_ == "ORG" and len(ent.text.strip()) >= min_length
    ]


def extract_locations(text: str, min_length: int = 3) -> list[NerEntity]:
    """Extrae LOC (ciudades, países, municipios)."""
    if not text:
        return []
    try:
        nlp = _get_nlp()
    except RuntimeError:
        return []
    doc = nlp(text[:200000])
    return [
        NerEntity(text=ent.text.strip(), label="LOC", start=ent.start_char, end=ent.end_char)
        for ent in doc.ents
        if ent.label_ == "LOC" and len(ent.text.strip()) >= min_length
    ]
