"""Tests del ANCLA DE FOOTER (fix 2026-06-03): `_footer_zone` re-lee la COLA del
documento del disco para que el footer 'Proyectó: <abogado>' no se pierda cuando el
`extracted_text` está capado a ~30k (solo cabeza). Espejo de `_dispositiva_zone`.

Diagnóstico de Wilson confirmado: el extractor de abogado leía el texto LINEAL/capado
(sin cola) → no hallaba el footer en respuestas largas. El ancla lo resuelve sin
re-extraer datos.
"""
import os
import tempfile
from types import SimpleNamespace

import pytest

from backend.v9.field_extractor import _footer_zone, _rp_abogado_footer

FOOTER = (
    "\nCordialmente,\n"
    "YANETH KARINA ARAUJO MAESTRE\nSECRETARIA DE EDUCACIÓN\n"
    "Proyectó: Luis Eduardo Meza Jurado - Abogado Especialista Grupo de Apoyo Jurídico.\n"
    "Aprobó: María Cristina Villamizar Schiller - Coordinadora Grupo de Apoyo Jurídico.\n"
)
BODY = ("CONTESTACIÓN DE TUTELA. " * 2000)  # ~46k chars → simula respuesta larga


def _make_docx(body: str, footer: str) -> str:
    from docx import Document as Docx
    doc = Docx()
    for chunk in body.split(". "):
        doc.add_paragraph(chunk)
    for line in footer.strip().splitlines():
        doc.add_paragraph(line)
    fd, path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    doc.save(path)
    return path


def test_footer_zone_recupera_el_proyecto_del_final():
    path = _make_docx(BODY, FOOTER)
    try:
        d = SimpleNamespace(file_path=path, id=1, extracted_text=BODY[:30000])
        zone = _footer_zone(d)
        assert zone and "Luis Eduardo Meza" in zone
        assert _rp_abogado_footer(zone) == "LUIS EDUARDO MEZA JURADO"
    finally:
        os.remove(path)


def test_extracted_text_capado_pierde_el_footer():
    # Prueba la CAUSA: el texto capado (solo cabeza, sin footer) NO da el redactor.
    # Es justo lo que el ancla de footer viene a arreglar.
    assert _rp_abogado_footer(BODY[:30000]) is None


def test_footer_zone_none_sin_filepath():
    d = SimpleNamespace(file_path=None, id=2, extracted_text="x")
    assert _footer_zone(d) is None


def test_footer_zone_none_archivo_inexistente():
    d = SimpleNamespace(file_path="/no/existe/foo.docx", id=3, extracted_text="x")
    assert _footer_zone(d) is None
