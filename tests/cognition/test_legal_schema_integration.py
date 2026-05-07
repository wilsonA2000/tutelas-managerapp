"""Tests de integración v9.4 — apply_deterministic_rules en pipeline.

Verifica:
1. Derivación juzgado_2nd con mapa judicial Santander
2. Clasificación SED por keyword (direccion/grupo/categoria_tematica)
3. Protección anti-sobreescritura (NO pisa valores existentes)
4. Regla solo dispara cuando aplica (impugnacion='SI')
"""
import pytest
from backend.cognition.agent.semantic_enricher import apply_deterministic_rules


def _make_case(**kwargs):
    """Construye un dict tipo Case ORM con defaults razonables."""
    base = {
        "id": 999, "asunto": None, "pretensiones": None, "accionados": None,
        "juzgado": None, "ciudad": None, "impugnacion": None,
        "juzgado_2nd": None, "direccion": None, "grupo": None, "equipo": None,
        "categoria_tematica": None,
    }
    base.update(kwargs)
    return base


def test_juzgado_2nd_derivado_san_andres_a_malaga():
    """Caso real Wilson: tutela en San Andrés sube al Circuito de Málaga."""
    case = _make_case(
        juzgado="Juzgado Promiscuo Municipal de San Andrés",
        accionados="Secretaría de Educación de Santander",
        ciudad="San Andrés",
        impugnacion="SI",
    )
    out = apply_deterministic_rules(case)
    assert "juzgado_2nd" in out
    assert "Málaga" in out["juzgado_2nd"]
    assert "Promiscuo del Circuito" in out["juzgado_2nd"]


def test_juzgado_2nd_no_dispara_sin_impugnacion():
    """No deriva juzgado_2nd si no hay impugnación SI."""
    case = _make_case(
        juzgado="Juzgado Civil Municipal de Bucaramanga",
        accionados="SED Santander",
        ciudad="Bucaramanga",
        impugnacion="NO",
    )
    out = apply_deterministic_rules(case)
    assert "juzgado_2nd" not in out


def test_no_sobreescribe_valor_existente():
    """Si juzgado_2nd ya tiene valor, no lo pisa."""
    case = _make_case(
        juzgado="Juzgado Promiscuo Municipal de San Andrés",
        ciudad="San Andrés",
        impugnacion="SI",
        juzgado_2nd="Tribunal Administrativo de Santander",  # valor existente
    )
    out = apply_deterministic_rules(case)
    # apply_deterministic_rules respeta el valor previo y no lo retorna
    assert "juzgado_2nd" not in out


def test_clasificacion_sed_traslado_docente():
    """Asunto 'traslado docente' → Talento Docente / Carrera Docente / TRASLADO."""
    case = _make_case(
        asunto="Solicita traslado docente por salud cónyuge",
        pretensiones="Que se ordene el traslado de la docente",
    )
    out = apply_deterministic_rules(case)
    assert out.get("direccion") == "DIRECCION_TALENTO_DOCENTE"
    assert out.get("grupo") == "CARRERA_DOCENTE"
    assert out.get("categoria_tematica") == "TRASLADO"


def test_clasificacion_sed_inclusion_discapacidad():
    """'tutor sombra' → Estratégica / Cobertura Educativa / TUTOR_SOMBRA."""
    case = _make_case(
        asunto="Solicita tutor sombra para niño con autismo",
        pretensiones="Que se asigne acompañante pedagógico",
    )
    out = apply_deterministic_rules(case)
    assert out.get("direccion") == "DIRECCION_ESTRATEGICA"
    assert out.get("grupo") == "COBERTURA_EDUCATIVA"
    assert out.get("categoria_tematica") == "TUTOR_SOMBRA"


def test_no_clasifica_sin_match():
    """Asunto sin keyword conocida → no rellena nada."""
    case = _make_case(
        asunto="Asunto totalmente atípico que no machea ningún patrón SED",
        pretensiones="Pretensiones genéricas",
    )
    out = apply_deterministic_rules(case)
    assert "direccion" not in out
    assert "grupo" not in out


def test_no_pisa_clasificacion_existente():
    """Si direccion ya está rellena, no la pisa."""
    case = _make_case(
        asunto="traslado docente",
        pretensiones="que se ordene traslado",
        direccion="VALOR_PREVIO_EXISTENTE",
    )
    out = apply_deterministic_rules(case)
    assert "direccion" not in out  # respeta existente
