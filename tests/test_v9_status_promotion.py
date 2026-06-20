"""Guard 2026-06-20: tras una extracción v9 aplicada con éxito, el status
PENDIENTE debe promoverse a COMPLETO (espeja routers/extraction.py), pero
REVISION / DUPLICATE_MERGED deben preservarse (flags humanos).

Sin esto, los casos curados quedaban stale en PENDIENTE → candidatas falsas
en la UI /extraction (260 casos observados en prod).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case
from backend.routers.v9 import _promote_status_on_success


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        Case(id=1, folder_name="c1 PENDIENTE", processing_status="PENDIENTE"),
        Case(id=2, folder_name="c2 REVISION", processing_status="REVISION"),
        Case(id=3, folder_name="c3 COMPLETO", processing_status="COMPLETO"),
        Case(id=4, folder_name="c4 DUP", processing_status="DUPLICATE_MERGED"),
    ])
    session.commit()
    yield session
    session.close()


def _status(db, cid):
    return db.query(Case).filter(Case.id == cid).first().processing_status


def test_pendiente_se_promueve_a_completo(db):
    _promote_status_on_success(db, 1)
    assert _status(db, 1) == "COMPLETO"


def test_revision_se_preserva(db):
    _promote_status_on_success(db, 2)
    assert _status(db, 2) == "REVISION"


def test_duplicate_merged_se_preserva(db):
    _promote_status_on_success(db, 4)
    assert _status(db, 4) == "DUPLICATE_MERGED"


def test_completo_idempotente(db):
    _promote_status_on_success(db, 3)
    assert _status(db, 3) == "COMPLETO"


def test_case_inexistente_no_rompe(db):
    _promote_status_on_success(db, 999)  # no debe lanzar
