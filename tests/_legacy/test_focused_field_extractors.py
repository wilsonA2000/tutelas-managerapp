"""Tests de focused_field_extractors con LLM mockeado."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.cognition.focused_field_extractors import (
    FocusedResult,
    extract_field_focused,
    extract_focused_for_case,
)


def _mock_llm(response_dict):
    """Devuelve un call_llm_fn que responde con el dict serializado."""
    raw = json.dumps(response_dict)
    return lambda messages: (raw, 50, 30)


# ============================================================
# quien_impugno
# ============================================================

def test_quien_impugno_accionante_valido():
    text = "El accionante presento recurso de impugnacion contra el fallo. " * 20
    r = extract_field_focused(
        "case", text, "quien_impugno",
        call_llm_fn=_mock_llm({"value": "ACCIONANTE", "confidence": "ALTA",
                                "quote": "El accionante presento recurso de impugnacion"}),
    )
    assert r.value == "ACCIONANTE"
    assert r.confidence >= 0.85
    assert r.rejected_reason is None


def test_quien_impugno_ministerio_publico_sin_evidencia_rechaza():
    """Anti-LoRA-bias: MINISTERIO_PUBLICO sin texto literal se descarta."""
    text = "Tutela negada. Accionante demanda. " * 30
    r = extract_field_focused(
        "case", text, "quien_impugno",
        call_llm_fn=_mock_llm({"value": "MINISTERIO_PUBLICO", "confidence": "ALTA",
                                "quote": "frase inventada"}),
    )
    assert r.value is None
    assert "MINISTERIO_PUBLICO" in r.rejected_reason


def test_quien_impugno_ministerio_publico_con_evidencia_acepta():
    text = "El procurador delegado interpuso impugnacion. " * 30
    r = extract_field_focused(
        "case", text, "quien_impugno",
        call_llm_fn=_mock_llm({"value": "MINISTERIO_PUBLICO", "confidence": "ALTA",
                                "quote": "El procurador delegado interpuso impugnacion"}),
    )
    assert r.value == "MINISTERIO_PUBLICO"


def test_quien_impugno_enum_invalido_rechaza():
    text = "X " * 200
    r = extract_field_focused(
        "case", text, "quien_impugno",
        call_llm_fn=_mock_llm({"value": "ALCALDE", "confidence": "ALTA", "quote": "X"}),
    )
    assert r.value is None
    assert "enum" in r.rejected_reason


# ============================================================
# fecha_apertura_incidente
# ============================================================

def test_fecha_apertura_valida():
    text = "El 15/03/2026 se presento el incidente de desacato. " * 30
    r = extract_field_focused(
        "case", text, "fecha_apertura_incidente",
        call_llm_fn=_mock_llm({"value": "15/03/2026", "confidence": "ALTA",
                                "quote": "El 15/03/2026 se presento el incidente"}),
    )
    assert r.value == "15/03/2026"


def test_fecha_apertura_formato_invalido_rechaza():
    text = "X " * 200
    r = extract_field_focused(
        "case", text, "fecha_apertura_incidente",
        call_llm_fn=_mock_llm({"value": "marzo 2026", "confidence": "ALTA", "quote": "X"}),
    )
    assert r.value is None
    assert "DD/MM/YYYY" in r.rejected_reason


def test_fecha_apertura_anio_imposible_rechaza():
    text = "X " * 200
    r = extract_field_focused(
        "case", text, "fecha_apertura_incidente",
        call_llm_fn=_mock_llm({"value": "01/01/1990", "confidence": "ALTA", "quote": "X"}),
    )
    assert r.value is None


# ============================================================
# juzgado_2nd
# ============================================================

def test_juzgado_2nd_valido():
    text = "TRIBUNAL SUPERIOR DE BUCARAMANGA SALA CIVIL. Confirma. " * 30
    r = extract_field_focused(
        "case", text, "juzgado_2nd",
        call_llm_fn=_mock_llm({"value": "TRIBUNAL SUPERIOR DE BUCARAMANGA SALA CIVIL",
                                "confidence": "ALTA",
                                "quote": "TRIBUNAL SUPERIOR DE BUCARAMANGA SALA CIVIL"}),
    )
    assert r.value == "TRIBUNAL SUPERIOR DE BUCARAMANGA SALA CIVIL"
    assert r.confidence > 0.7


def test_juzgado_2nd_jurisprudencia_rechaza():
    """Si la cita parece jurisprudencia (Sentencia T-XXX), descartar."""
    text = "Texto largo. " * 50
    r = extract_field_focused(
        "case", text, "juzgado_2nd",
        call_llm_fn=_mock_llm({"value": "CORTE CONSTITUCIONAL SALA PRIMERA",
                                "confidence": "ALTA",
                                "quote": "Sentencia T-123/2020 de la Corte Constitucional"}),
    )
    assert r.value is None
    assert "jurisprudencia" in r.rejected_reason


def test_juzgado_2nd_no_tribunal_rechaza():
    text = "X " * 200
    r = extract_field_focused(
        "case", text, "juzgado_2nd",
        call_llm_fn=_mock_llm({"value": "Despacho del Procurador General",
                                "confidence": "ALTA", "quote": "X"}),
    )
    assert r.value is None


# ============================================================
# sentido_fallo_2nd
# ============================================================

def test_sentido_fallo_2nd_valido():
    text = "X " * 200
    r = extract_field_focused(
        "case", text, "sentido_fallo_2nd",
        call_llm_fn=_mock_llm({"value": "CONFIRMA", "confidence": "ALTA", "quote": "X"}),
    )
    assert r.value == "CONFIRMA"


def test_sentido_fallo_2nd_enum_invalido_rechaza():
    text = "X " * 200
    r = extract_field_focused(
        "case", text, "sentido_fallo_2nd",
        call_llm_fn=_mock_llm({"value": "ACEPTA", "confidence": "ALTA", "quote": "X"}),
    )
    assert r.value is None


# ============================================================
# responsable_desacato
# ============================================================

def test_responsable_desacato_valido():
    text = "Secretario de Educacion JUAN PEREZ es señalado como responsable. " * 20
    r = extract_field_focused(
        "case", text, "responsable_desacato",
        call_llm_fn=_mock_llm({"value": "Secretario de Educacion JUAN PEREZ",
                                "confidence": "ALTA",
                                "quote": "Secretario de Educacion JUAN PEREZ"}),
    )
    assert "JUAN PEREZ" in r.value


def test_responsable_desacato_corto_rechaza():
    text = "X " * 200
    r = extract_field_focused(
        "case", text, "responsable_desacato",
        call_llm_fn=_mock_llm({"value": "Juan", "confidence": "ALTA", "quote": "X"}),
    )
    assert r.value is None


# ============================================================
# Cita literal: penalizacion si no aparece
# ============================================================

def test_quote_invented_penalizes_confidence():
    """Si la cita NO aparece en el texto, confidence se reduce a la mitad."""
    text = "TRIBUNAL SUPERIOR DE BOGOTA SALA CIVIL. " * 30
    r = extract_field_focused(
        "case", text, "juzgado_2nd",
        call_llm_fn=_mock_llm({"value": "TRIBUNAL SUPERIOR DE BUCARAMANGA SALA CIVIL",
                                "confidence": "ALTA",
                                "quote": "esta frase no esta en el texto en ningun lado xyz"}),
    )
    # Quote no aparece => confidence reducida; value puede pasar pero con penalty
    assert r.confidence < 0.7 or r.value is None


# ============================================================
# extract_focused_for_case (orchestrator)
# ============================================================

def test_extract_focused_skips_existing_fields():
    case = SimpleNamespace(
        accionante="A", juzgado="J", impugnacion="SI", incidente="NO",
        sentido_fallo_1st="NIEGA",
        quien_impugno="ACCIONANTE",  # YA tiene valor
        juzgado_2nd=None, sentido_fallo_2nd=None,
        fecha_apertura_incidente=None, responsable_desacato=None,
    )
    text = "X " * 200
    out = extract_focused_for_case(case, text, call_llm_fn=_mock_llm({"value": None}))
    assert "quien_impugno" not in out  # ya tenia valor


def test_extract_focused_skips_inapplicable_fields():
    """Si impugnacion=NO, no se piden campos de impugnacion."""
    case = SimpleNamespace(
        accionante="A", juzgado="J", impugnacion="NO", incidente="NO",
        sentido_fallo_1st="NIEGA",
        quien_impugno=None, juzgado_2nd=None, sentido_fallo_2nd=None,
        fecha_apertura_incidente=None, responsable_desacato=None,
    )
    text = "X " * 200
    called = []
    def mock(msgs):
        called.append(1)
        return json.dumps({"value": None}), 0, 0
    out = extract_focused_for_case(case, text, call_llm_fn=mock)
    assert out == {}
    assert called == []  # ningun campo aplica
