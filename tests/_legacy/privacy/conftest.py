"""Fixtures comunes para tests de privacidad."""

import pytest


SAMPLE_AUTO_ADMISORIO = """\
Bucaramanga, 15 de marzo de 2026. La accionante Paola Andrea García Núñez,
identificada con CC 63.498.732, actuando en nombre de su hija menor Sofía García
(RC 1.098.765.432, 8 años), residente en Calle 45 #23-10 barrio San Francisco,
contra la Secretaría de Educación de Santander, por vulneración del derecho
a la educación de su hija diagnosticada con parálisis cerebral (CIE-10 G80.9).
Teléfono de contacto: 3204992211. Correo: paola.garcia@gmail.com.
"""

SAMPLE_RESPONSE = """\
RESPUESTA FOREST 20260054965. El Juzgado Primero Promiscuo Municipal de
Bucaramanga admitió la tutela radicada bajo 68001400902720260003400.
Proyectó: Luis Eduardo Meza Jurado. Accionante: Paola Andrea García Núñez.
"""


@pytest.fixture
def sample_docs():
    return [
        {"filename": "auto_admisorio.pdf", "text": SAMPLE_AUTO_ADMISORIO},
        {"filename": "respuesta.docx", "text": SAMPLE_RESPONSE},
    ]


@pytest.fixture
def known_entities():
    return {
        "PERSON": ["Paola Andrea García Núñez", "Sofía García", "Luis Eduardo Meza Jurado"],
        "CC": ["63.498.732"],
        "NUIP": ["1.098.765.432"],
        "RADICADO_FOREST": ["20260054965"],
    }
