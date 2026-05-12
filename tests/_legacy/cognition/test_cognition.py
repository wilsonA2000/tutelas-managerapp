"""Tests del módulo cognitivo (v5.3.1)."""

import pytest

from backend.cognition import (
    classify_zones, extract_actors, infer_derechos_from_dx,
    extract_decision, build_asunto, build_pretensiones,
    build_observaciones, build_derecho_vulnerado, cognitive_fill,
)


SAMPLE_AUTO = """\
Juzgado Doce Penal Municipal con Función de Control de Garantías de Bucaramanga
Bucaramanga, catorce (14) de abril de dos mil veintiséis (2026)

Examinado el escrito de tutela, dado que reúne los requisitos, ADMÍTASE esta
acción interpuesta por SEIDE YANETH TARAZONA PABON como agente oficiosa de su
hijo JUAN SEBASTIAN MALDONADO TARAZONA, para la protección de sus derechos
fundamentales de educación, debido proceso y salud, en consecuencia, dése
TRASLADO al representante legal de la INSTITUCION EDUCATIVA GUSTAVO COTE URIBE
y SALUD TOTAL EPS. De oficio vincúlese a la SECRETARIA DE EDUCACION DE SANTANDER,
ALCALDIA DE BUCARAMANGA Y GOBERNACION DE SANTANDER.
"""

SAMPLE_SENTENCIA = """\
RESUELVE

PRIMERO: TUTELAR los derechos fundamentales a la educación y la salud invocados.
SEGUNDO: ORDENAR a la SECRETARÍA DE EDUCACIÓN cumplir con la medida en 48 horas.

Dada en Bucaramanga el 20 de abril de 2026.
"""


def test_zone_classifier_detects_admite():
    zones = classify_zones(SAMPLE_AUTO)
    assert zones.has("encabezado")
    assert zones.has("admite")


def test_zone_classifier_detects_resuelve():
    zones = classify_zones(SAMPLE_SENTENCIA)
    assert zones.has("resuelve")


def test_entity_extractor_finds_accionante():
    actors = extract_actors(SAMPLE_AUTO, classify_zones(SAMPLE_AUTO))
    names = [a.name for a in actors.accionantes]
    assert any("SEIDE" in n and "TARAZONA" in n for n in names)


def test_entity_extractor_finds_minor():
    actors = extract_actors(SAMPLE_AUTO, classify_zones(SAMPLE_AUTO))
    names = [a.name for a in actors.menores]
    assert any("JUAN SEBASTIAN" in n for n in names)


def test_cie10_parálisis_cerebral_infers_derechos():
    text = "El menor tiene parálisis cerebral (CIE-10 G80.9) y requiere silla de ruedas."
    ds = infer_derechos_from_dx(text)
    assert "SALUD" in ds
    assert "VIDA DIGNA" in ds
    assert "DIGNIDAD HUMANA" in ds


def test_cie10_keyword_docente_infers_laboral():
    text = "Solicita el traslado docente por razones de amenaza."
    ds = infer_derechos_from_dx(text)
    assert "EDUCACION" in ds
    assert "TRABAJO" in ds or "DEBIDO PROCESO" in ds


def test_decision_extractor_detects_concede():
    dec = extract_decision(SAMPLE_SENTENCIA, classify_zones(SAMPLE_SENTENCIA))
    assert dec.sentido == "CONCEDE"
    assert dec.fecha == "20/04/2026"


def test_decision_extractor_detects_niega():
    text = "RESUELVE\nPRIMERO: NEGAR el amparo solicitado.\nDada el 5 de mayo de 2026."
    dec = extract_decision(text, classify_zones(text))
    assert dec.sentido == "NIEGA"
    assert dec.fecha == "05/05/2026"


def test_narrative_builder_asunto_from_traslado():
    from backend.cognition import ActorSet
    from backend.cognition.entity_extractor import Actor
    actors = ActorSet(
        accionantes=[Actor(role="ACCIONANTE", name="Pedro Pérez", confidence=0.9)],
        accionados=[Actor(role="ACCIONADO", name="SECRETARÍA DE EDUCACIÓN", confidence=0.8)],
    )
    asunto = build_asunto(actors, "EDUCACION - TRABAJO",
                          "Solicito traslado docente por seguridad personal")
    assert "traslado docente" in asunto.lower()


def test_narrative_observaciones_has_cronologia():
    from backend.cognition import ActorSet
    from backend.cognition.entity_extractor import Actor
    from backend.cognition.decision_extractor import Decision
    actors = ActorSet(
        accionantes=[Actor(role="ACCIONANTE", name="Ana García", confidence=0.9)],
        accionados=[Actor(role="ACCIONADO", name="NUEVA EPS", confidence=0.8)],
    )
    dec = Decision(sentido="CONCEDE", fecha="15/04/2026", impugnacion="NO")
    obs = build_observaciones(actors, "SALUD - VIDA DIGNA", dec, {
        "fecha_ingreso": "10/04/2026",
        "radicado_23_digitos": "68-001-40-XX",
        "radicado_forest": "20260012345",
        "abogado_responsable": "Juan Abogado",
    })
    assert "Ana García" in obs
    assert "NUEVA EPS" in obs
    assert "15/04/2026" in obs
    assert "FOREST" in obs and "20260012345" in obs


def test_cognitive_fill_returns_extractionresults():
    from backend.agent.extractors.base import ExtractionResult
    meta = {"id": 1, "fecha_ingreso": "14/04/2026",
            "radicado_23_digitos": "", "radicado_forest": "",
            "abogado_responsable": "", "incidente": ""}
    results = cognitive_fill(meta, SAMPLE_AUTO, existing={})
    assert len(results) > 0
    assert "accionante" in results
    assert isinstance(results["accionante"], ExtractionResult)
    assert results["accionante"].method == "cognition"


def test_cognitive_fill_respects_high_confidence_regex():
    """Si regex ya dio accionante con confianza >=80, cognición no sobrescribe."""
    from backend.agent.extractors.base import ExtractionResult
    existing = {
        "accionante": ExtractionResult(
            value="REGEX DEFINITIVO NAME", confidence=95,
            source="regex", method="regex", reasoning="test",
        ),
    }
    meta = {"id": 1, "fecha_ingreso": "", "radicado_23_digitos": "",
            "radicado_forest": "", "abogado_responsable": "", "incidente": ""}
    results = cognitive_fill(meta, SAMPLE_AUTO, existing=existing)
    # accionante no debe estar en results (respeta regex existing)
    assert "accionante" not in results
