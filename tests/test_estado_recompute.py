"""persist: `estado` (campo DERIVADO) se RECOMPUTA en re-extracción (no fill-only),
PERO un valor MANUAL se respeta. Regresión del bug destapado por la ingesta real:
al llenar nuevos sentido/incidente, el estado quedaba stale."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case
from backend.v9.persist import persist
from backend.v9.types import ExtractedFields, FieldSource


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'estado.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)()


def _fields_estado(val):
    f = ExtractedFields()
    f.set("estado", val, FieldSource.REGEX)
    return f


def test_estado_se_recomputa_aunque_tenga_valor(db):
    """estado stale (INACTIVO) se recomputa al re-extraer (ACTIVO)."""
    c = Case(folder_name="2026-00001 TEST", processing_status="COMPLETO", estado="INACTIVO")
    db.add(c); db.flush()
    persist(db, c.id, _fields_estado("ACTIVO"), dry_run=False)
    db.refresh(c)
    assert c.estado == "ACTIVO"  # recomputado (NO fill-only)


def test_estado_manual_se_respeta(db):
    """estado curado a mano (v9_sources=manual) NO se pisa en re-extracción."""
    c = Case(folder_name="2026-00001 TEST", processing_status="COMPLETO", estado="ACTIVO",
             field_confidences_json=json.dumps({"v9_sources": {"estado": "manual"}}))
    db.add(c); db.flush()
    persist(db, c.id, _fields_estado("INACTIVO"), dry_run=False)
    db.refresh(c)
    assert c.estado == "ACTIVO"  # MANUAL protegido


def test_campo_normal_sigue_fill_only(db):
    """un campo NO derivado (ej. accionados) mantiene fill-only (no se pisa)."""
    c = Case(folder_name="2026-00001 TEST", processing_status="COMPLETO", accionados="JUAN PEREZ")
    db.add(c); db.flush()
    f = ExtractedFields()
    f.set("accionados", "OTRO DISTINTO", FieldSource.REGEX)
    persist(db, c.id, f, dry_run=False)
    db.refresh(c)
    assert c.accionados == "JUAN PEREZ"  # fill-only intacto
