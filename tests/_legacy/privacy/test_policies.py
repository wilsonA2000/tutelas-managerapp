"""Tests de políticas selective vs aggressive (v5.3)."""

from backend.privacy.policies import (
    AGGRESSIVE_KINDS, SELECTIVE_KINDS, should_redact,
)


def test_selective_is_subset_of_aggressive():
    assert SELECTIVE_KINDS <= AGGRESSIVE_KINDS


def test_selective_includes_numeric_identifiers():
    for kind in ("CC", "NUIP", "PHONE", "EMAIL", "ADDRESS_EXACT"):
        assert should_redact(kind, "selective"), f"{kind} debería redactar en selective"


def test_selective_preserves_names_and_cities():
    for kind in ("PERSON", "CITY_EXACT", "COURT_EXACT", "ORG_SENSITIVE"):
        assert not should_redact(kind, "selective"), f"{kind} NO debería redactar en selective"


def test_aggressive_redacts_everything_in_selective():
    for kind in SELECTIVE_KINDS:
        assert should_redact(kind, "aggressive")


def test_aggressive_redacts_semantic_content():
    for kind in ("PERSON", "DX_DETAIL", "RADICADO_FOREST", "CITY_EXACT"):
        assert should_redact(kind, "aggressive")
