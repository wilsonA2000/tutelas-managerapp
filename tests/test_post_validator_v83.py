"""Tests F11/F12/F13 anadidas al post_validator en v8.3."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.extraction.post_validator import validate_extraction


def make_case(**kw):
    defaults = dict(
        folder_name="2026-00001 TEST", radicado_23_digitos=None, radicado_forest=None,
        impugnacion=None, juzgado=None, juzgado_2nd=None,
        fecha_ingreso=None, fecha_fallo_1st=None, fecha_fallo_2nd=None,
        fecha_apertura_incidente=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


# ============================================================
# F11: impugnacion=NO ⇒ fallo_2nd vacio
# ============================================================

def test_F11_impugnacion_no_limpia_fallo_2nd():
    case = make_case(impugnacion="NO")
    fields = {
        "impugnacion": "NO",
        "sentido_fallo_2nd": "CONFIRMA",
        "juzgado_2nd": "TRIBUNAL X",
        "fecha_fallo_2nd": "01/03/2026",
    }
    corrected, warnings = validate_extraction(case, fields)
    assert corrected.get("sentido_fallo_2nd") == ""
    assert corrected.get("juzgado_2nd") == ""
    assert corrected.get("fecha_fallo_2nd") == ""
    assert any("F11" in w for w in warnings)


def test_F11_impugnacion_si_no_toca_fallo_2nd():
    case = make_case(impugnacion="SI")
    fields = {"impugnacion": "SI", "sentido_fallo_2nd": "CONFIRMA"}
    corrected, _ = validate_extraction(case, fields)
    assert "sentido_fallo_2nd" not in corrected


def test_F11_lee_impugnacion_de_case_si_no_en_fields():
    case = make_case(impugnacion="NO")
    fields = {"sentido_fallo_2nd": "REVOCA"}
    corrected, warnings = validate_extraction(case, fields)
    assert corrected.get("sentido_fallo_2nd") == ""


# ============================================================
# F12: juzgado != juzgado_2nd
# ============================================================

def test_F12_juzgados_iguales_limpia_2nd():
    case = make_case(juzgado="JUZGADO PROMISCUO MUNICIPAL DE BETULIA")
    fields = {
        "juzgado": "JUZGADO PROMISCUO MUNICIPAL DE BETULIA",
        "juzgado_2nd": "JUZGADO PROMISCUO MUNICIPAL DE BETULIA",
    }
    corrected, warnings = validate_extraction(case, fields)
    assert corrected.get("juzgado_2nd") == ""
    assert any("F12" in w for w in warnings)


def test_F12_juzgados_distintos_no_toca():
    case = make_case()
    fields = {"juzgado": "JUZGADO X", "juzgado_2nd": "TRIBUNAL Y"}
    corrected, _ = validate_extraction(case, fields)
    assert "juzgado_2nd" not in corrected


# ============================================================
# F13: orden cronológico
# ============================================================

def test_F13_fallo_1st_anterior_a_ingreso_solo_warning():
    """v8.3.1: F13 NO modifica, solo emite warning."""
    case = make_case()
    fields = {
        "fecha_ingreso": "15/03/2026",
        "fecha_fallo_1st": "01/02/2026",
    }
    corrected, warnings = validate_extraction(case, fields)
    assert "fecha_fallo_1st" not in corrected  # NO se modifica
    assert any("F13" in w and "REVISAR" in w for w in warnings)


def test_F13_fallo_2nd_anterior_a_fallo_1st_solo_warning():
    case = make_case()
    fields = {
        "fecha_ingreso": "01/02/2026",
        "fecha_fallo_1st": "15/03/2026",
        "fecha_fallo_2nd": "01/03/2026",
    }
    corrected, warnings = validate_extraction(case, fields)
    assert "fecha_fallo_2nd" not in corrected
    assert any("F13" in w for w in warnings)


def test_F13_fechas_ordenadas_no_toca():
    case = make_case()
    fields = {
        "fecha_ingreso": "01/02/2026",
        "fecha_fallo_1st": "15/03/2026",
        "fecha_fallo_2nd": "01/05/2026",
    }
    corrected, warnings = validate_extraction(case, fields)
    for f in ("fecha_ingreso", "fecha_fallo_1st", "fecha_fallo_2nd"):
        assert f not in corrected


def test_F13_skip_fechas_invalidas():
    case = make_case()
    fields = {
        "fecha_ingreso": "fecha invalida",
        "fecha_fallo_1st": "15/03/2026",
    }
    corrected, _ = validate_extraction(case, fields)
    assert "fecha_fallo_1st" not in corrected
