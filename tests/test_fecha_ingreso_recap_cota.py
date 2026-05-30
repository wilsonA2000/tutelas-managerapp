"""Cota del recap de fecha_ingreso: la admisión SIEMPRE precede al fallo.

Regresión: en folders incidente-only, el modo `recap` de extract_fecha_ingreso
captaba fechas de incidente/requerimiento citadas en docs (posteriores o futuras
al fallo) como fecha_ingreso → fecha_fallo_1st < fecha_ingreso (imposible).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case, Document
from backend.v9.field_extractor import extract_fecha_ingreso_for_case

RAD_2026 = "68001408900120260001000"  # año (pos 12-15) = 2026


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'recap.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)()


def _mk_case(db, **kw):
    c = Case(folder_name="2026-00002 TEST", processing_status="COMPLETO",
             radicado_23_digitos=RAD_2026, **kw)
    db.add(c); db.flush()
    return c


def test_recap_posterior_al_fallo_se_rechaza(db):
    """recap 12/03/2026 citado en doc de incidente, fallo 13/02/2026 → NO se usa."""
    c = _mk_case(db, fecha_fallo_1st="13/02/2026")
    db.add(Document(
        case_id=c.id, filename="autoreq.pdf", file_path="/tmp/autoreq.pdf",
        doc_type="INCIDENTE_DESACATO",
        extracted_text="Mediante auto admisorio del 12 de marzo de 2026 se avocó conocimiento.",
    ))
    db.flush()
    val, src = extract_fecha_ingreso_for_case(db, c)
    assert val != "12/03/2026"  # la cota rechaza el recap posterior al fallo


def test_recap_anterior_al_fallo_se_acepta(db):
    """recap 20/01/2026 (antes del fallo 13/02) SÍ es la admisión válida."""
    c = _mk_case(db, fecha_fallo_1st="13/02/2026")
    db.add(Document(
        case_id=c.id, filename="fallo.pdf", file_path="/tmp/fallo.pdf",
        doc_type="SENTENCIA_1RA",
        extracted_text="Mediante auto admisorio del 20 de enero de 2026 se admitió la tutela.",
    ))
    db.flush()
    val, src = extract_fecha_ingreso_for_case(db, c)
    assert val == "20/01/2026"
    assert src == "recap"
