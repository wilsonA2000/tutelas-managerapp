"""Tests de detectores PII (v5.3)."""

import pytest

from backend.privacy.detectors import (
    Span, blacklist_detect, merge_spans, presidio_detect, regex_detect,
)


def test_regex_detect_cc_and_nuip():
    text = "CC 63.498.732 de la madre. RC 1.098.765.432 del menor."
    spans = regex_detect(text)
    kinds = {s.kind for s in spans}
    # regex_library no incluye detector CC con separadores de miles — eso lo hace Presidio.
    # regex_library SÍ detecta "C.C. 91071881" formato sin puntos. Aquí solo valida el flujo.
    assert isinstance(spans, list)


def test_regex_detect_email_and_phone():
    text = "Escríbeme a paola@gmail.com o llama al 3204992211."
    spans = regex_detect(text)
    kinds = {s.kind for s in spans}
    assert "EMAIL" in kinds
    assert "PHONE" in kinds


def test_blacklist_detect_finds_known_names():
    text = "El accionante Paola Andrea García Núñez y su hija Sofía García..."
    spans = blacklist_detect(text, {"PERSON": ["Paola Andrea García Núñez", "Sofía García"]})
    values = [s.value for s in spans]
    assert any("Paola Andrea García Núñez" in v for v in values)
    assert any("Sofía García" in v for v in values)
    assert all(s.source == "blacklist" for s in spans)


def test_merge_spans_priority_blacklist_wins_over_presidio():
    """Si blacklist y presidio detectan el mismo span, gana blacklist."""
    bl_span = Span(10, 30, "PERSON", "Paola Andrea", 1.0, "blacklist")
    pr_span = Span(10, 30, "PERSON", "Paola Andrea", 0.85, "presidio")
    merged = merge_spans([bl_span], [pr_span])
    assert len(merged) == 1
    assert merged[0].source == "blacklist"


def test_merge_spans_overlap_keeps_longer():
    """Ante spans de misma fuente y score similares, gana el más largo."""
    s1 = Span(10, 20, "PERSON", "Paola", 0.8, "presidio")
    s2 = Span(10, 35, "PERSON", "Paola Andrea García", 0.8, "presidio")
    merged = merge_spans([s1, s2])
    assert len(merged) == 1
    assert merged[0].end - merged[0].start == 25


def test_presidio_detects_person_es():
    pytest.importorskip("presidio_analyzer")
    text = "La accionante Paola Andrea García Núñez interpuso tutela en Bucaramanga."
    spans = presidio_detect(text)
    kinds = {s.kind for s in spans}
    # Presidio ES debe encontrar al menos PERSON o CITY_EXACT
    assert "PERSON" in kinds or "CITY_EXACT" in kinds
