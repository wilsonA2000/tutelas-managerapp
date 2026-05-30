"""Regresión: _is_segunda_instancia decide por el VERBO DISPOSITIVO del primer
ordinal (no por el boilerplate del encabezado). Una sentencia de 1ra que menciona
"segunda instancia"/"Tribunal Superior" en los derechos de impugnación NO debe
clasificarse como 2da (falso+ que perdía su resolutiva y su sentido)."""
from types import SimpleNamespace

from backend.v9.field_extractor import _is_segunda_instancia


def _doc(filename, text):
    return SimpleNamespace(filename=filename, file_path=None, extracted_text=text)


def test_1ra_con_boilerplate_segunda_instancia_no_es_2da():
    d = _doc(
        "016SentenciaTutela.pdf",
        "JUZGADO PROMISCUO MUNICIPAL. El presente fallo podrá impugnarse para que "
        "surta la SEGUNDA INSTANCIA ante el TRIBUNAL SUPERIOR del Distrito. " * 6
        + "RESUELVE: PRIMERO.- TUTELAR el derecho fundamental de petición del "
        "accionante. NOTIFÍQUESE Y CÚMPLASE",
    )
    assert _is_segunda_instancia(d) is False


def test_2da_dispositiva_confirmar_es_2da():
    d = _doc(
        "FalloTutela.pdf",
        "RESUELVE: PRIMERO: CONFIRMAR el fallo proferido por el a-quo. "
        "NOTIFÍQUESE Y CÚMPLASE",
    )
    assert _is_segunda_instancia(d) is True


def test_2da_dispositiva_revocar_es_2da():
    d = _doc(
        "Impugnacion.pdf",
        "RESUELVE: PRIMERO: REVOCAR el fallo proferido el 07 de abril de 2026. "
        "NOTIFÍQUESE Y CÚMPLASE",
    )
    assert _is_segunda_instancia(d) is True
