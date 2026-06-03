"""Tests del fix 2026-06-02 a `_extract_forest`: el FOREST de SED es year-prefixed
(20YY...) o formato nuevo GESTA (N-20YY-DEP-CONS). Rechaza el radicado judicial
(68...) y los Proc#/IDs legacy de 7 díg que se colaban por "RADICACIÓN #".
"""
from backend.v9.regex_pass import _extract_forest


def test_rechaza_judicial_68_en_radicacion():
    assert _extract_forest("AL RESPONDER CITE RADICACIÓN # : 6800122130002 GOBERNACION") is None


def test_doc_con_judicial_primero_y_forest_despues():
    # finditer: judicial 68 primero, FOREST 2026 después → devuelve el FOREST.
    txt = "RADICACIÓN # : 682764189006 ... mas abajo RADICACIÓN #: 20260099893"
    assert _extract_forest(txt) == "20260099893"


def test_canonico_year_prefixed():
    assert _extract_forest("Con número de radicado 20260069713. Cordialmente") == "20260069713"


def test_proc_legacy_7dig_rechazado():
    assert _extract_forest("Proc # : 2821568 RADICACIÓN # : 2821568") is None


def test_formato_nuevo_gesta_intacto():
    assert _extract_forest("Radicado: 2-2026-104200-000508 GESTA") == "2-2026-104200-000508"


def test_continuo_2025_valido():
    assert _extract_forest("RADICACIÓN #: 20250048292") == "20250048292"
