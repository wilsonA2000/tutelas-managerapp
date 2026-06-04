"""Tests de las anclas de retrieval (`backend/v9/field_context._window`).

Cubren el hueco identificado en el diagnóstico 2026-06-03 (0 tests de field_context) y
blindan el refuerzo de la Fase 3 (la dispositiva "PRIMERO: <verbo>" sin keyword RESUELVE).
"""
from backend.v9.field_context import _window


def test_ancla_demanda_pretensiones():
    pages = ["carátula", "PRETENSIONES: ordene a la SED el reintegro", "anexos"]
    win = _window(pages, "demanda")
    assert win is not None and win[0] <= 1 < win[1]


def test_ancla_resuelve_keyword():
    pages = ["hechos", "considerandos", "RESUELVE:\nPRIMERO: TUTELAR el derecho"]
    win = _window(pages, "resuelve")
    assert win is not None and 2 in range(win[0], win[1])


def test_ancla_resuelve_primero_sin_keyword():
    # Fase 3: dispositiva que numera sin encabezado RESUELVE → el patrón PRIMERO:<verbo> la pesca.
    pages = ["solicitud", "valoración", "PRIMERO: NEGAR por improcedente la acción de tutela.\nSEGUNDO: notificar."]
    win = _window(pages, "resuelve")
    assert win is not None, "la dispositiva 'PRIMERO: NEGAR' sin RESUELVE debe anclarse"


def test_resuelve_usa_ultima_ocurrencia():
    # which='last': evita el falso positivo de menciones a media frase, toma la dispositiva final.
    pages = ["la providencia que resuelve el recurso", "x", "RESUELVE:\nPRIMERO: CONCEDER"]
    win = _window(pages, "resuelve")
    assert win is not None and win[1] >= 3  # ventana ancla en la última (pág 2, idx)


def test_sin_ancla_devuelve_none():
    assert _window(["pura carátula", "sellos", "firmas"], "resuelve") is None
