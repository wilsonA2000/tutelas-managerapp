"""Señal 'reparto_email' del extractor de abogado_responsable (2026-06-12).

Regla Wilson: la tutela, al asignarse al abogado de la SED, va en el correo al
abogado en reparto. El correo PERSONAL del roster cuenta solo como DESTINATARIO
(Para/Cc); como remitente suele ser el apoderado del accionante (caso real c238).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case, Document
from backend.v9.field_extractor import _abogado_from_reparto_email, _roster_email_map


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _mk(db, email_text, doc_type="EMAIL_MD"):
    c = Case(folder_name="2026-00999 TEST")
    db.add(c); db.commit()
    d = Document(case_id=c.id, filename="Email_test.md", file_path="/tmp/Email_test.md",
                 doc_type=doc_type, extracted_text=email_text)
    db.add(d); db.commit()
    return c


def test_roster_tiene_correos_de_abogados():
    emap = _roster_email_map()
    assert "mezajuradoabogados@gmail.com" in emap
    assert "angelicabarrososarmiento@gmail.com" in emap  # correo_alterno
    # técnicos/bachilleres del grupo NO llevan casos
    assert "jdsv2409@hotmail.com" not in emap


def test_destinatario_cc_asigna(db):
    c = _mk(db, "De: Apoyo Jurídico <apoyojuridicosed@santander.gov.co>\n"
                "Para: Juridica Th <x@santander.gov.co>\n"
                "Cc: Luis Eduardo Meza Jurado <mezajuradoabogados@gmail.com>\n"
                "Asunto: RV: AUTO AVOCA")
    assert _abogado_from_reparto_email(db, c) == "LUIS EDUARDO MEZA JURADO"


def test_remitente_no_cuenta(db):
    # gmail del roster como REMITENTE = apoderado del accionante (c238) → None
    c = _mk(db, "De: Luis Eduardo Meza Jurado <mezajuradoabogados@gmail.com>\n"
                "Para: Juzgado 01 <j01@cendoj.ramajudicial.gov.co>\n"
                "Asunto: demanda de tutela")
    assert _abogado_from_reparto_email(db, c) is None


def test_empate_es_ambiguo(db):
    c = _mk(db, "Para: a <mezajuradoabogados@gmail.com>\n"
                "Cc: b <angelicabarrososarmiento@gmail.com>\n")
    assert _abogado_from_reparto_email(db, c) is None
