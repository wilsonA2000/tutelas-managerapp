"""Detectores de PII combinados: Presidio ES + regex propios + blacklist del caso (v5.3)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

from backend.core.settings import settings

_logger = logging.getLogger("tutelas.privacy.detectors")


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    kind: str        # CC / NUIP / PERSON / ORG / PHONE / EMAIL / ADDRESS_EXACT / RADICADO_FOREST / DX_DETAIL / ...
    value: str
    score: float     # 0-1 confianza
    source: str      # "blacklist" / "regex" / "presidio"


# ============================================================
# Presidio
# ============================================================

# Mapeo entidad Presidio → kind interno.
# LOCATION va a CITY_EXACT (solo aggressive). Las direcciones con estructura
# ("Calle X #Y-Z") se detectan vía ADDRESS_EXACT_RECOGNIZER custom.
_PRESIDIO_ENTITY_MAP = {
    "PERSON": "PERSON",
    "LOCATION": "CITY_EXACT",
    "ORGANIZATION": "ORG_SENSITIVE",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "CC": "CC",
    "NUIP": "NUIP",
    "RADICADO_FOREST": "RADICADO_FOREST",
    "DX_DETAIL": "DX_DETAIL",
    "ADDRESS_EXACT": "ADDRESS_EXACT",
}

_PRESIDIO_ENTITIES = list(_PRESIDIO_ENTITY_MAP.keys())


@lru_cache(maxsize=1)
def _get_analyzer():
    """Construye un AnalyzerEngine con NLP ES + recognizers custom. Singleton."""
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from backend.privacy.presets_es import CUSTOM_RECOGNIZERS
    except ImportError as e:
        raise RuntimeError(f"Presidio no instalado: {e}. Corre `pip install presidio-analyzer presidio-anonymizer`")

    nlp_config = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "es", "model_name": settings.PII_PRESIDIO_MODEL}],
    }
    provider = NlpEngineProvider(nlp_configuration=nlp_config)
    nlp_engine = provider.create_engine()

    analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["es"])
    for rec in CUSTOM_RECOGNIZERS:
        analyzer.registry.add_recognizer(rec)
    return analyzer


def presidio_detect(text: str) -> list[Span]:
    """Detecta PII con Presidio ES + recognizers custom."""
    if not text:
        return []
    try:
        analyzer = _get_analyzer()
    except RuntimeError as e:
        _logger.error("Presidio no disponible: %s", e)
        return []
    results = analyzer.analyze(text=text, language="es", entities=_PRESIDIO_ENTITIES)
    spans: list[Span] = []
    for r in results:
        kind = _PRESIDIO_ENTITY_MAP.get(r.entity_type, r.entity_type)
        spans.append(Span(
            start=r.start, end=r.end, kind=kind,
            value=text[r.start:r.end], score=float(r.score),
            source="presidio",
        ))
    return spans


# ============================================================
# Regex propios (reutiliza patrones del proyecto)
# ============================================================

# Mapeo patrón del proyecto → kind PII
_REGEX_KIND_MAP = {
    "cc_accionante": "CC",
    "nuip_menor": "NUIP",
    "forest_specific": "RADICADO_FOREST",
    "forest_keyword": "RADICADO_FOREST",
}


def regex_detect(text: str) -> list[Span]:
    """Detecta PII con los patrones regex del propio proyecto.

    Reutiliza `backend.agent.regex_library.ALL_PATTERNS` para no duplicar
    lógica ya testada con los 394 casos reales.
    """
    if not text:
        return []
    try:
        from backend.agent.regex_library import ALL_PATTERNS
    except ImportError:
        return []

    spans: list[Span] = []
    for pat in ALL_PATTERNS:
        kind = _REGEX_KIND_MAP.get(pat.name)
        if not kind:
            continue
        for m in pat.pattern.finditer(text):
            g_start, g_end = (m.start(1), m.end(1)) if m.groups() else (m.start(), m.end())
            spans.append(Span(
                start=g_start, end=g_end, kind=kind,
                value=text[g_start:g_end], score=0.95,
                source="regex",
            ))
    # Email y teléfono genéricos (no están en regex_library)
    for m in re.finditer(r"[\w\.\-\+]+@[\w\.\-]+\.\w{2,}", text):
        spans.append(Span(m.start(), m.end(), "EMAIL", m.group(), 0.9, "regex"))
    # Móvil estándar 10 dígitos
    for m in re.finditer(r"\b3[0-5]\d[\s\-]?\d{3}[\s\-]?\d{4}\b", text):
        spans.append(Span(m.start(), m.end(), "PHONE", m.group(), 0.85, "regex"))
    # Móvil con OCR sucio (9 dígitos precedido por "Tel.:" o similar)
    for m in re.finditer(r"(?:Tel\.?|Tel[eé]fono|Cel\.?|Celular|M[oó]vil|Contacto|WhatsApp)[\s:\.]+(3\d{7,9})\b", text, re.IGNORECASE):
        num_s = m.start(1); num_e = m.end(1)
        spans.append(Span(num_s, num_e, "PHONE", m.group(1), 0.75, "regex"))

    # CC formato `1.096961643` (común en Santander OCR)
    from backend.privacy.calibration import detect_cc_single_dot, detect_tercero_entries
    for s, e, val in detect_cc_single_dot(text):
        spans.append(Span(s, e, "CC", val, 0.95, "regex"))
    # Tercero: <CC> <NOMBRE> — captura CC (el nombre va al blacklist del caso)
    for cc, _name, s, e in detect_tercero_entries(text):
        # offset del solo número dentro del match completo
        num_s = text.find(cc, s)
        if num_s >= 0:
            spans.append(Span(num_s, num_s + len(cc), "CC", cc, 0.9, "regex"))

    # Filtrar falsos positivos contextuales sobre spans CC detectados
    from backend.privacy.calibration import is_false_positive_cc
    spans = [
        s for s in spans
        if not (s.kind == "CC" and is_false_positive_cc(s.value, text, s.start, s.end))
    ]
    return spans


# ============================================================
# Blacklist del caso (deterministic override)
# ============================================================

def blacklist_detect(text: str, known: dict[str, list[str]]) -> list[Span]:
    """Detecta valores ya identificados por regex/forensic en otras fases.

    `known` es dict kind → [valores]. Por ejemplo:
        {"PERSON": ["Paola Andrea García Núñez", "María Rodríguez"],
         "CC": ["63498732"]}

    Los matches de blacklist tienen score=1.0 y prioridad máxima en merge_spans.
    """
    if not text or not known:
        return []
    spans: list[Span] = []
    for kind, values in known.items():
        for v in values:
            if not v or len(v.strip()) < 3:
                continue
            pat = re.compile(re.escape(v.strip()), re.IGNORECASE)
            for m in pat.finditer(text):
                spans.append(Span(m.start(), m.end(), kind, m.group(), 1.0, "blacklist"))
    return spans


# ============================================================
# Merge de spans con precedencia
# ============================================================

_SOURCE_PRIORITY = {"blacklist": 3, "regex": 2, "presidio": 1}


def merge_spans(*span_lists: list[Span]) -> list[Span]:
    """Combina detecciones de múltiples fuentes.

    Reglas:
    - Si 2 spans solapan: gana el de mayor prioridad de fuente (blacklist > regex > presidio).
    - Si misma prioridad: gana el de mayor score; si empate, el más largo.
    - Spans ordenados por `start` ascendente al retornar.
    """
    all_spans: list[Span] = []
    for lst in span_lists:
        all_spans.extend(lst)
    if not all_spans:
        return []

    # Ordenar por (start, -length) para procesar de izq a der
    all_spans.sort(key=lambda s: (s.start, -(s.end - s.start)))

    result: list[Span] = []
    for span in all_spans:
        if not result:
            result.append(span)
            continue
        last = result[-1]
        if span.start >= last.end:
            result.append(span)
            continue
        # Overlap — resolver
        if _beats(span, last):
            result[-1] = span
    return result


def _beats(new: Span, old: Span) -> bool:
    pn = _SOURCE_PRIORITY.get(new.source, 0)
    po = _SOURCE_PRIORITY.get(old.source, 0)
    if pn != po:
        return pn > po
    if abs(new.score - old.score) > 0.05:
        return new.score > old.score
    return (new.end - new.start) > (old.end - old.start)
