"""Regresión 2026-06-12: fallos FRESCOS de la ingesta no se capturaban.

Dos causas reales (casos c516/c530/c534):
1. La ingesta clasifica los fallos como PDF_SENTENCIA (filename-based) y los
   extractores de 1ª instancia solo leían doc_type SENTENCIA_1RA.
2. `_dispositiva_zone` re-lee la cola del PDF desde disco; en PDFs ESCANEADOS
   (texto en DB vía OCR) la cola viene vacía y no caía al texto almacenado.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case, Document
from backend.v9.field_extractor import (
    extract_sentido_fallo_1ra_for_case, _sentencia_1ra_docs,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


FALLO_TXT = (
    "JUZGADO PROMISCUO MUNICIPAL\nSENTENCIA DE TUTELA\n" + ("relato de antecedentes. " * 60) +
    "\nRESUELVE: PRIMERO: Declarar Improcedente la Acción de Tutela impetrada por "
    "la señora PRUEBA PEREZ contra la SECRETARIA DE EDUCACION, por no agotar el "
    "requisito de subsidiariedad. SEGUNDO: NOTIFICAR a las partes. "
    "NOTIFÍQUESE Y CÚMPLASE"
)


def _mk(db, doc_type, filename, text=FALLO_TXT, file_path="/tmp/no-existe-escaneado.pdf"):
    c = Case(folder_name="2026-00777 PRUEBA PEREZ")
    db.add(c); db.commit()
    d = Document(case_id=c.id, filename=filename, file_path=file_path,
                 doc_type=doc_type, extracted_text=text)
    db.add(d); db.commit()
    return c


def test_pdf_sentencia_fresco_si_extrae(db):
    # El tipo que produce la ingesta (PDF_SENTENCIA) debe ser candidato.
    c = _mk(db, "PDF_SENTENCIA", "20Sentencia.pdf")
    s, src = extract_sentido_fallo_1ra_for_case(db, c)
    assert s == "IMPROCEDENTE"
    assert src == "sentencia"


def test_sentencia_1ra_clasica_sigue_funcionando(db):
    c = _mk(db, "SENTENCIA_1RA", "009SentenciaPrimeraInstancia.pdf")
    s, _ = extract_sentido_fallo_1ra_for_case(db, c)
    assert s == "IMPROCEDENTE"


def test_artefacto_notificacion_excluido(db):
    # "OficioNotificaFallo" rotulado PDF_SENTENCIA NO es candidato (es la notificación).
    c = _mk(db, "PDF_SENTENCIA", "14OficioNotificaFalloTutela.pdf")
    assert _sentencia_1ra_docs(db, c) == []


def test_pdf_escaneado_cae_a_texto_db(db):
    # file_path .pdf inexistente (≅ escaneado sin capa de texto): la cola del disco
    # viene vacía → debe caer al extracted_text de DB (que vino del OCR de ingesta).
    c = _mk(db, "PDF_SENTENCIA", "Sentencia.pdf", file_path="/tmp/zz-no-existe.pdf")
    s, _ = extract_sentido_fallo_1ra_for_case(db, c)
    assert s == "IMPROCEDENTE"
