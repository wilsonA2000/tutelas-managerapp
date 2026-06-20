"""Guard 2026-06-20: normalize_juzgado_cpnu convierte el numeral CPNU del nombre del
juzgado ('008') a la forma curada colombiana ('OCTAVO') para que activar el enrich de
Rama Judicial NO degrade el formato de los 433 juzgados curados."""

from __future__ import annotations

import pytest

from backend.v9.rama_judicial_enrich import normalize_juzgado_cpnu


@pytest.mark.parametrize("raw,esperado", [
    # casos reales observados en la prueba CPNU 2026-06-20
    ("JUZGADO 008 ADMINISTRATIVO  DE BUCARAMANGA", "JUZGADO OCTAVO ADMINISTRATIVO DE BUCARAMANGA"),
    ("JUZGADO 001 PROMISCUO MUNICIPAL DE SABANA DE TORRES",
     "JUZGADO PRIMERO PROMISCUO MUNICIPAL DE SABANA DE TORRES"),
    # ordinales 1-10
    ("JUZGADO 010 CIVIL", "JUZGADO DÉCIMO CIVIL"),
    # cardinales 11+
    ("JUZGADO 011 CIVIL DEL CIRCUITO", "JUZGADO ONCE CIVIL DEL CIRCUITO"),
    ("JUZGADO 023 PENAL MUNICIPAL", "JUZGADO VEINTITRÉS PENAL MUNICIPAL"),
    ("JUZGADO 31 LABORAL", "JUZGADO TREINTA Y UNO LABORAL"),
])
def test_normaliza_numeral(raw, esperado):
    assert normalize_juzgado_cpnu(raw) == esperado


def test_fuera_de_rango_se_deja(self_=None):
    # >40 no está en el mapa → conserva el numeral (solo limpia espacios)
    assert normalize_juzgado_cpnu("JUZGADO 099 ESPECIAL") == "JUZGADO 099 ESPECIAL"


def test_sin_numeral_no_cambia():
    assert normalize_juzgado_cpnu("TRIBUNAL ADMINISTRATIVO DE SANTANDER") == \
        "TRIBUNAL ADMINISTRATIVO DE SANTANDER"
    # ya en forma ordinal → intacto
    assert normalize_juzgado_cpnu("JUZGADO OCTAVO ADMINISTRATIVO") == "JUZGADO OCTAVO ADMINISTRATIVO"


def test_none_y_vacio():
    assert normalize_juzgado_cpnu(None) is None
    assert normalize_juzgado_cpnu("") == ""
