"""Ciclo de vida de extracción (2026-06-12) — autoridad derivada.

estado_extraccion compara field_confidences_json.v9_extracted_at del case
contra documents.created_at: NUNCA_EXTRAIDO / DESACTUALIZADO / AL_DIA.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case, Document
from backend.services.case_service import estado_extraccion, _case_review_flags


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


NOW = datetime(2026, 6, 12, 12, 0, 0)


def _case(db, extracted_at=None, **kw):
    fc = json.dumps({"v9_extracted_at": extracted_at.isoformat()}) if extracted_at else None
    c = Case(folder_name=kw.pop("folder_name", "2026-00900 PRUEBA"),
             field_confidences_json=fc, **kw)
    db.add(c); db.commit()
    return c


def _doc(db, case, created_at):
    d = Document(case_id=case.id, filename="x.pdf", file_path="/tmp/x.pdf",
                 doc_type="PDF_OTRO", created_at=created_at)
    db.add(d); db.commit()
    return d


def test_caso_nuevo_es_candidata(db):
    c = _case(db)  # sin v9_extracted_at, sin campos → completitud baja
    _doc(db, c, NOW)
    r = estado_extraccion(db, c)
    assert r["estado"] == "NUNCA_EXTRAIDO"
    assert r["last_extraction_at"] is None


def test_docs_posteriores_es_desactualizado(db):
    c = _case(db, extracted_at=NOW - timedelta(days=3))
    _doc(db, c, NOW - timedelta(days=5))   # anterior — no cuenta
    _doc(db, c, NOW - timedelta(hours=1))  # posterior — dispara
    r = estado_extraccion(db, c)
    assert r["estado"] == "DESACTUALIZADO"
    assert r["docs_nuevos"] == 1


def test_extraido_sin_docs_nuevos_al_dia(db):
    c = _case(db, extracted_at=NOW)
    _doc(db, c, NOW - timedelta(days=1))
    r = estado_extraccion(db, c)
    assert r["estado"] == "AL_DIA"
    assert r["docs_nuevos"] == 0


def test_docs_legacy_sin_created_at_no_disparan(db):
    # Docs pre-migración (created_at NULL) se tratan como antiguos. El ORM
    # aplica server_default al insertar → se fuerza NULL con UPDATE crudo,
    # que es exactamente como existen las filas legacy reales.
    from sqlalchemy import text
    c = _case(db, extracted_at=NOW - timedelta(days=3))
    d = _doc(db, c, NOW)
    db.execute(text("UPDATE documents SET created_at = NULL WHERE id = :i"), {"i": d.id})
    db.commit()
    db.expire_all()
    r = estado_extraccion(db, c)
    assert r["estado"] == "AL_DIA"


def test_flag_docs_nuevos_en_review_flags(db):
    c = _case(db, extracted_at=NOW - timedelta(days=3))
    _doc(db, c, NOW)
    f = _case_review_flags(c)
    assert f["docs_nuevos"] is True
    c2 = _case(db, folder_name="2026-00901 OTRA", extracted_at=NOW)
    _doc(db, c2, NOW - timedelta(days=1))
    assert _case_review_flags(c2)["docs_nuevos"] is False
