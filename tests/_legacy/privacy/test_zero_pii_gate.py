"""Tests del gate zero-PII (v5.3)."""

import pytest

from backend.privacy.zero_pii_gate import assert_clean, Violation


def test_clean_payload_no_violations():
    docs = [{"filename": "a.txt", "text": "Sin datos sensibles aquí. Solo [ACCIONANTE_1] y [CC_####1234]."}]
    v = assert_clean(docs, mode="selective")
    assert v == []


def test_cc_with_dots_triggers_violation():
    docs = [{"filename": "a.txt", "text": "CC 63.498.732 sin tokenizar."}]
    v = assert_clean(docs, mode="selective")
    assert any(vi.kind == "CC" for vi in v)


def test_bare_cc_triggers_violation():
    docs = [{"filename": "a.txt", "text": "El número es 1098765432 aislado."}]
    v = assert_clean(docs, mode="selective")
    assert any(vi.kind == "CC_BARE" for vi in v)


def test_phone_mobile_triggers_violation():
    docs = [{"filename": "a.txt", "text": "Contacto: 3204992211"}]
    v = assert_clean(docs, mode="selective")
    assert any(vi.kind == "PHONE" for vi in v)


def test_email_triggers_violation():
    docs = [{"filename": "a.txt", "text": "escribe a paola@gmail.com"}]
    v = assert_clean(docs, mode="selective")
    assert any(vi.kind == "EMAIL" for vi in v)


def test_address_exact_triggers_violation():
    docs = [{"filename": "a.txt", "text": "Reside en Calle 45 #23-10 barrio San Francisco."}]
    v = assert_clean(docs, mode="selective")
    assert any(vi.kind == "ADDRESS_EXACT" for vi in v)


def test_aggressive_mode_detects_known_person_leak():
    docs = [{"filename": "a.txt", "text": "El caso de Paola Andrea García Núñez es sensible."}]
    v = assert_clean(docs, mode="aggressive", known_entities={"PERSON": ["Paola Andrea García Núñez"]})
    assert any(vi.kind == "PERSON_LEAK" for vi in v)


def test_selective_mode_allows_names():
    """En selective, los nombres son OK (no violación)."""
    docs = [{"filename": "a.txt", "text": "El caso de Paola Andrea García Núñez es sensible."}]
    v = assert_clean(docs, mode="selective", known_entities={"PERSON": ["Paola Andrea García Núñez"]})
    # Solo chequea identificadores numéricos en selective → no hay violación de nombres
    assert all(vi.kind != "PERSON_LEAK" for vi in v)


def test_tokens_inside_brackets_are_not_flagged():
    """Los contenidos de tokens [...] se ignoran al validar."""
    docs = [{"filename": "a.txt", "text": "[CC_####5432] es el token, no una CC real."}]
    v = assert_clean(docs, mode="selective")
    assert v == []


def test_forest_11_digit_not_flagged_in_selective():
    """Radicado FOREST (11d empezando por 2026) se permite crudo en selective."""
    docs = [{"filename": "a.txt", "text": "Radicado FOREST 20260054965 del caso."}]
    v = assert_clean(docs, mode="selective")
    assert all(vi.value != "20260054965" for vi in v)
