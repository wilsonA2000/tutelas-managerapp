"""Tests E2E v9.4 — endpoints REST nuevos (sin Qwen up requerido).

Cubre:
- /api/cognitive/status (read-only, sin estado)
- /api/cognitive/enrich-deterministic-batch (sin tokens)
- /api/intelligence/similar/{id} (BGE-M3 puro)
- legal_schema deriva juzgado_2nd según factor funcional
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.main import app
    return TestClient(app)


def test_cognitive_status_responds_200(client):
    """Endpoint status no requiere Qwen y debe siempre responder."""
    r = client.get("/api/cognitive/status")
    assert r.status_code == 200
    data = r.json()
    assert "state" in data
    assert "paddleocr_up" in data
    assert "qwen_up" in data
    assert isinstance(data["transitioning"], bool)


def test_cognitive_enrich_targets_lists_v94_targets(client):
    """Lista de targets debe incluir los nuevos v9.4 (verbatim, ciudad)."""
    r = client.get("/api/cognitive/enrich/targets")
    assert r.status_code == 200
    targets = r.json()
    assert "pretensiones_verbatim" in targets
    assert "ciudad_vulneracion" in targets
    assert "responsable_desacato" in targets


def test_intelligence_similar_endpoint_responds(client):
    """/api/intelligence/similar/{id} con BGE-M3 (sin Qwen)."""
    r = client.get("/api/intelligence/similar/1?k=3&source=historical")
    # 200 o 404/422 si el caso no existe — todos válidos
    assert r.status_code in (200, 404, 422, 503)
    if r.status_code == 200:
        data = r.json()
        assert "neighbors" in data
        assert "consensus" in data
        assert "reasoning" in data


def test_legal_schema_san_andres_a_malaga():
    """Caso real Wilson: san andres → circuito málaga (factor funcional)."""
    from backend.cognition.legal_schema import derivar_juzgado_segunda
    r = derivar_juzgado_segunda(
        "Juzgado Promiscuo Municipal de San Andrés",
        "Secretaría de Educación de Santander",
        "San Andrés",
    )
    assert r is not None
    assert "Málaga" in r.juzgado_2nd
    assert "Promiscuo del Circuito" in r.juzgado_2nd


def test_legal_schema_administrativo_circuito_a_tribunal():
    """Juzgado Administrativo del Circuito → Tribunal Administrativo de Santander."""
    from backend.cognition.legal_schema import derivar_juzgado_segunda
    r = derivar_juzgado_segunda(
        "Juzgado Quinto Administrativo del Circuito de Bucaramanga",
        "SED",
        "Bucaramanga",
    )
    assert r is not None
    assert "Tribunal Administrativo de Santander" == r.juzgado_2nd


def test_legal_schema_no_pisa_valor_existente():
    """apply_deterministic_rules respeta valores ya rellenos."""
    from backend.cognition.agent.semantic_enricher import apply_deterministic_rules
    case = {
        "id": 999,
        "asunto": "traslado docente", "pretensiones": "que se ordene",
        "accionados": None, "juzgado": None, "ciudad": None, "impugnacion": None,
        "juzgado_2nd": None,
        "direccion": "VALOR_PREVIO",  # ya tenía
        "grupo": None, "equipo": None, "categoria_tematica": None,
    }
    out = apply_deterministic_rules(case)
    assert "direccion" not in out  # no debe pisar


def test_pretensiones_verbatim_extrae_seccion_clara():
    """build_pretensiones (v9.4 VERBATIM) copia literal, no parafrasea."""
    from backend.cognition.narrative_builder import build_pretensiones

    class _A:
        accionados = []; accionante = None
    full = """
    HECHOS
    bla bla

    PRETENSIONES
    PRIMERA: Tutelar el derecho fundamental a la educación.
    SEGUNDA: Ordenar a la SED el traslado.

    FUNDAMENTOS DE DERECHO
    Constitución Política, art. 86.
    """
    out = build_pretensiones(_A(), "EDUCACION", full, "traslado")
    assert "PRIMERA" in out
    assert "SEGUNDA" in out
    assert "Tutelar el derecho fundamental" in out
    assert "FUNDAMENTOS DE DERECHO" not in out  # corte limpio
    # NO debe contener paráfrasis fallback
    assert "Que se ordene el traslado docente a la institución solicitada" not in out


def test_forensic_deprecated_warnings_emit(recwarn):
    """Las funciones legacy emiten DeprecationWarning."""
    from backend.services.forensic_analyzer import (
        classify_by_content, extract_all_identifiers, extract_entities,
    )
    classify_by_content("texto")
    extract_all_identifiers("rad 12345-12345")
    extract_entities("texto")
    # Al menos 3 deprecation warnings
    deps = [w for w in recwarn if issubclass(w.category, DeprecationWarning)]
    assert len(deps) >= 3
