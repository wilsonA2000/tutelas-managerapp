"""Test de integración: pipeline completo no envía PII a IA (v5.3)."""

import re

import pytest


def _has_cc_dots(text: str) -> bool:
    return bool(re.search(r"\b\d{1,3}\.\d{3}\.\d{3}\b", text))


def _has_bare_cc(text: str) -> bool:
    return bool(re.search(r"\b\d{8,10}\b", text))


def _has_mobile(text: str) -> bool:
    return bool(re.search(r"\b3[0-5]\d{8}\b", text))


def _has_email(text: str) -> bool:
    return bool(re.search(r"[\w\.]+@[\w\.]+\.\w+", text))


def test_redacted_payload_has_no_numeric_pii():
    """Verifica que el flujo redact_payload elimine CC, tel, email del texto."""
    from backend.privacy import redact_payload, RedactionContext

    docs = [{
        "filename": "test.txt",
        "text": (
            "CC 63.498.732 de la madre. Tel 3204992211. Email paola@gmail.com. "
            "RC 1.098.765.432 del menor. Dir Calle 45 #23-10."
        ),
    }]
    ctx = RedactionContext(case_id=1, mode="selective", known_entities={})
    out = redact_payload(docs, ctx)
    full = " ".join(d["text"] for d in out.docs)
    assert not _has_cc_dots(full), f"CC con puntos filtró: {full}"
    assert not _has_mobile(full), f"Móvil filtró: {full}"
    assert not _has_email(full), f"Email filtró: {full}"


def test_collect_known_entities_builds_blacklist():
    """_collect_known_entities debe sacar nombres de regex_results y del case."""
    from backend.extraction.unified import _collect_known_entities
    from backend.agent.extractors.base import ExtractionResult

    class FakeCase:
        accionante = "Paola Andrea García"
        abogado_responsable = "Luis Meza"
        radicado_forest = "20260054965"

    regex_results = {
        "accionante": ExtractionResult(
            value="Paola Andrea García", confidence=95, source="r",
            method="regex", reasoning="test",
        ),
    }
    known = _collect_known_entities(regex_results, FakeCase())
    assert "Paola Andrea García" in known["PERSON"]
    assert "Luis Meza" in known["PERSON"]
    assert "20260054965" in known["RADICADO_FOREST"]


def test_settings_pii_defaults():
    """Verifica que los settings PII_* están cargados correctamente."""
    from backend.core.settings import settings
    assert settings.PII_REDACTION_ENABLED is True
    assert settings.PII_MODE_DEFAULT in ("selective", "aggressive")
    assert settings.PII_PRESIDIO_MODEL in ("es_core_news_md", "es_core_news_lg")
