"""Tests del redactor (v5.3)."""

import pytest
import re

from backend.privacy import redact_payload, RedactionContext, assert_clean


def test_selective_mode_masks_numeric_identifiers(sample_docs, known_entities):
    ctx = RedactionContext(case_id=1, mode="selective", known_entities=known_entities)
    out = redact_payload(sample_docs, ctx)

    full = " ".join(d["text"] for d in out.docs)
    # Identificadores numéricos → deben haber desaparecido
    assert "63.498.732" not in full
    assert "1.098.765.432" not in full
    assert "3204992211" not in full
    assert "paola.garcia@gmail.com" not in full


def test_selective_mode_preserves_names_and_cities(sample_docs, known_entities):
    ctx = RedactionContext(case_id=1, mode="selective", known_entities=known_entities)
    out = redact_payload(sample_docs, ctx)
    full = " ".join(d["text"] for d in out.docs)
    # Nombres y ciudad se quedan en selective (son públicos)
    assert "Paola Andrea García Núñez" in full
    assert "Bucaramanga" in full


def test_aggressive_mode_masks_everything(sample_docs, known_entities):
    ctx = RedactionContext(case_id=1, mode="aggressive", known_entities=known_entities)
    out = redact_payload(sample_docs, ctx)
    full = " ".join(d["text"] for d in out.docs)
    # Nombres, CC, NUIP, ciudad, FOREST, diagnóstico: todo tokenizado
    assert "Paola Andrea García Núñez" not in full
    assert "Sofía García" not in full
    assert "63.498.732" not in full
    assert "20260054965" not in full


def test_whitelist_preserves_institutional_names(sample_docs, known_entities):
    ctx = RedactionContext(case_id=1, mode="aggressive", known_entities=known_entities)
    out = redact_payload(sample_docs, ctx)
    full = " ".join(d["text"] for d in out.docs)
    # Secretaría de Educación, Santander, Gobernación, no deben tokenizarse
    assert "Secretaría de Educación" in full or "Santander" in full


def test_tokens_appear_in_output(sample_docs, known_entities):
    ctx = RedactionContext(case_id=1, mode="aggressive", known_entities=known_entities)
    out = redact_payload(sample_docs, ctx)
    full = " ".join(d["text"] for d in out.docs)
    # Al menos un token acuñado debe aparecer
    assert re.search(r"\[[A-Z]", full) is not None


def test_zero_pii_violations_in_both_modes(sample_docs, known_entities):
    for mode in ("selective", "aggressive"):
        ctx = RedactionContext(case_id=1, mode=mode, known_entities=known_entities)
        out = redact_payload(sample_docs, ctx)
        v = assert_clean(out.docs, mode=mode, known_entities=known_entities)
        assert v == [], f"Violaciones en modo {mode}: {v}"


def test_mapping_is_non_empty_when_pii_present(sample_docs, known_entities):
    ctx = RedactionContext(case_id=1, mode="selective", known_entities=known_entities)
    out = redact_payload(sample_docs, ctx)
    assert len(out.mapping) >= 1
    for token, info in out.mapping.items():
        assert token.startswith("[") and token.endswith("]")
        assert "value" in info and "kind" in info
