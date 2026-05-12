"""Tests adicionales de decision_extractor tras iteración +2/+3 (v5.3.2)."""

import pytest

from backend.cognition import classify_zones, extract_decision


def test_tutelese_imperative_form():
    """Fallo con 'TUTÉLESE' (imperativa) debe detectarse como CONCEDE."""
    text = """RESUELVE
    PRIMERO.- TUTÉLESE los derechos fundamentales a la educación.
    Dado en Bucaramanga el 5 de mayo de 2026."""
    dec = extract_decision(text, classify_zones(text))
    assert dec.sentido == "CONCEDE"
    assert dec.fecha == "05/05/2026"


def test_amparese_imperative():
    text = """RESUELVE\nPRIMERO: AMPÁRESE el derecho a la salud. Dada el 10 de junio de 2026."""
    dec = extract_decision(text, classify_zones(text))
    assert dec.sentido == "CONCEDE"


def test_niegase_imperative():
    text = """RESUELVE\nPRIMERO: NIÉGUESE el amparo solicitado. Bucaramanga, 3 de marzo de 2026."""
    dec = extract_decision(text, classify_zones(text))
    assert dec.sentido == "NIEGA"


def test_anchored_date_proferido():
    text = "La sentencia fue proferida el 15 de abril de 2026 por el juzgado."
    dec = extract_decision(text, classify_zones(text))
    # Si no hay RESUELVE, el extractor podría no capturar sentido; pero la fecha debería anclarse
    # a un verbo de decisión si existe en texto adyacente
    # Este test verifica que el pattern anchored date funciona al menos en el parser helper
    from backend.cognition.decision_extractor import _find_anchored_fallo_date
    d = _find_anchored_fallo_date(text, 0, window=500)
    assert d == "15/04/2026"


def test_anchored_date_mediante_fallo():
    text = "El accionante fue amparado mediante fallo del 20/04/2026 que concedió la tutela."
    from backend.cognition.decision_extractor import _find_anchored_fallo_date
    d = _find_anchored_fallo_date(text, 0, window=500)
    assert d == "20/04/2026"


def test_parcial_priority_when_near():
    """CONCEDE PARCIALMENTE debe ganar si aparece cerca de CONCEDE."""
    text = """RESUELVE
    PRIMERO: CONCEDE PARCIALMENTE la tutela por los motivos expuestos.
    Dada el 1 de enero de 2026."""
    dec = extract_decision(text, classify_zones(text))
    assert dec.sentido == "CONCEDE PARCIALMENTE"


def test_hecho_superado_as_improcedente():
    """Carencia actual de objeto / hecho superado = IMPROCEDENTE."""
    text = """RESUELVE
    PRIMERO: Declarar hecho superado la presente acción de tutela.
    Bucaramanga, 10 de octubre de 2025."""
    dec = extract_decision(text, classify_zones(text))
    assert dec.sentido == "IMPROCEDENTE"


def test_primero_delimita_busqueda():
    """Un documento con IMPROCEDENTE en el resumen doctrinal y TUTELAR en PRIMERO
    debe capturar TUTELAR (la decisión real)."""
    text = """Antecedentes: se mencionó que en casos similares se declaró IMPROCEDENTE.
    Sin embargo, en el presente caso:
    RESUELVE
    PRIMERO: TUTELAR los derechos fundamentales invocados.
    Dada el 15 de marzo de 2026."""
    dec = extract_decision(text, classify_zones(text))
    assert dec.sentido == "CONCEDE"
