"""Tests del guard canónico en `_clean_responsable_desacato` (field_extractor v9).

Regla c456 (feedback_abogado_responsable, mem 2026-05-18): `responsable_desacato`
es el abogado SED que proyectó la respuesta al incidente — debe ser uno de los
17 oficiales en `backend/data/abogados_canonicos.json`. Cargos / instituciones / nombres
externos → None. Antes del fix (2026-05-28), la función aceptaba cargos genéricos
(Secretaria, Director, Gobernador) y devolvía uppercase, lo que produjo 69 casos
con valores no-canónicos (auditor lo detectó).
"""
from backend.v9.field_extractor import _clean_responsable_desacato


def test_canonico_pasa():
    """Un nombre que está en el catálogo de 17 → devuelve la versión canónica."""
    r = _clean_responsable_desacato("ANGELICA BARROSO SARMIENTO")
    assert r == "ANGELICA YADIRA BARROSO SARMIENTO"


def test_canonico_con_titulo_pasa():
    """Doctor/Dra/funcionario al inicio se limpian y el nombre canónico pasa."""
    r = _clean_responsable_desacato("Dra. Victor Alfonso Colmenares Niño")
    assert r and "VICTOR ALFONSO COLMENARES" in r


def test_canonico_fuzzy_pasa():
    """Pequeñas variaciones (tildes/typos) que el roster fuzzy resuelve."""
    r = _clean_responsable_desacato("OTILIA LUNA LOPEZ")
    assert r == "OTILIA LUNA LOPEZ"


def test_cargo_secretaria_rechazado():
    """Cargo 'Secretaria de Educación' (sin nombre canónico) → None.
    Antes del fix devolvía 'SECRETARIA DE EDUCACIÓN...' uppercase."""
    assert _clean_responsable_desacato("Secretaria de Educación de Santander") is None
    assert _clean_responsable_desacato("Director de Talento Humano") is None
    assert _clean_responsable_desacato("Coordinadora Grupo Apoyo Jurídico") is None


def test_institucion_rechazada():
    """Instituciones puras → None (no son responsable_desacato)."""
    assert _clean_responsable_desacato("SECRETARÍA DE EDUCACIÓN DEPARTAMENTAL DE SANTANDER") is None
    assert _clean_responsable_desacato("GOBERNACIÓN DE SANTANDER") is None
    assert _clean_responsable_desacato("MINISTERIO DE EDUCACIÓN NACIONAL") is None


def test_persona_no_canonica_rechazada():
    """Nombre propio que NO está en el catálogo → None.
    YANETH KARINA ARAUJO MAESTRE es la Secretaria de Educación (cargo, no canónica).
    JUVENAL DÍAZ MATEUS es el Gobernador.
    Ninguno de los dos en el roster de 17 abogados."""
    assert _clean_responsable_desacato("YANETH KARINA ARAUJO MAESTRE") is None
    assert _clean_responsable_desacato("JUVENAL DÍAZ MATEUS") is None
    # Funcionarios externos sin pertenencia al Grupo Jurídico
    assert _clean_responsable_desacato("JIMMI NOE GÓMEZ SEPÚLVEDA") is None
    assert _clean_responsable_desacato("DAISY JOHANNA FLOREZ SIMANCA") is None


def test_vacio_y_basura_rechazados():
    """Valores triviales/basura."""
    assert _clean_responsable_desacato("") is None
    assert _clean_responsable_desacato(None) is None
    assert _clean_responsable_desacato("INCIDENTE DE DESACATO") is None
    assert _clean_responsable_desacato("ACCIONADOS Y VINCULADOS") is None


def test_longitud_fuera_rango():
    """Strings muy cortos (<6 chars) o muy largos (>80 chars) rechazados antes
    de llegar al validador canónico."""
    assert _clean_responsable_desacato("ABC") is None
    assert _clean_responsable_desacato("X" * 90) is None
