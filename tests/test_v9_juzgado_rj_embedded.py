"""Test del fix 2026-06-02 de `extract_juzgado_for_case`:

El remitente Rama Judicial (cendoj/notificacionesrj) que trae el municipio suele venir
EMBEBIDO en un PDF de demanda/auto forwarded o en el `sender` del email, no solo en los
.md EMAIL_JUDICIAL. Antes `_rj_sender_candidates` solo miraba EMAIL_JUDICIAL/EMAIL_INTERNO
→ juzgados incompletos sin municipio (c411/c369/c219…). Ahora escanea cualquier doc +
emails.sender, y el ranking MUNICIPAL>CIRCUITO resuelve los casos con varios remitentes.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case, Document, Email
from backend.v9.field_extractor import extract_juzgado_for_case


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _case_with_doc(db, doc_type, text):
    c = Case(folder_name="2026-00001 PRUEBA", processing_status="PENDIENTE")
    db.add(c); db.commit(); db.refresh(c)
    db.add(Document(case_id=c.id, filename="x.pdf", file_path="/tmp/x.pdf",
                    doc_type=doc_type, extracted_text=text))
    db.commit()
    return c


def test_rj_sender_embebido_en_demanda_recupera_municipio(db):
    # El remitente RJ viene dentro del texto de una DEMANDA_TUTELA (email forwarded en PDF),
    # NO en un EMAIL_JUDICIAL → antes se perdía el municipio.
    txt = ("ACCION DE TUTELA\nDe: Juzgado 04 Civil Circuito - Santander - Bucaramanga "
           "<j04ccbuc@cendoj.ramajudicial.gov.co>\nPara: tutelas@santander.gov.co\n"
           "Señor juez, acudo ante usted...")
    c = _case_with_doc(db, "DEMANDA_TUTELA", txt)
    j = extract_juzgado_for_case(db, c)
    assert j and "BUCARAMANGA" in j.upper(), j
    assert "CUARTO" in j.upper() or "04" in j


def test_ranking_municipal_gana_a_circuito(db):
    # Dos remitentes RJ: 1ra instancia municipal (El Peñón) + 2da circuito (Vélez).
    # Debe ganar el MUNICIPAL (la 1ra instancia que lleva la tutela).
    txt = ("Juzgado 01 Promiscuo Municipal - Santander - El Peñón <jprmpalelpenon@cendoj.ramajudicial.gov.co>\n"
           "Juzgado 02 Promiscuo Familia Circuito - Santander - Vélez <j02pfvelez@cendoj.ramajudicial.gov.co>")
    c = _case_with_doc(db, "AUTO_ADMISORIO", txt)
    j = extract_juzgado_for_case(db, c)
    assert j and "PEÑÓN" in j.upper(), j
    assert "VÉLEZ" not in j.upper(), j


def test_rj_sender_en_campo_email_sender(db):
    # El remitente RJ viene en el campo emails.sender (no en texto de doc).
    c = Case(folder_name="2026-00002 PRUEBA", processing_status="PENDIENTE")
    db.add(c); db.commit(); db.refresh(c)
    db.add(Email(case_id=c.id, message_id="m1",
                 sender="Juzgado 16 Civil Municipal - Santander - Bucaramanga <j16cmbuc@cendoj.ramajudicial.gov.co>",
                 subject="NOTIFICACION"))
    db.commit()
    j = extract_juzgado_for_case(db, c)
    assert j and "BUCARAMANGA" in j.upper(), j
