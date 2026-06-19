"""Tests de sync de actuaciones CPNU → case_actuaciones (Fase C)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case, CaseActuacion
from backend.services.rama_judicial_sync import sync_case_actuaciones, SOURCE


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _case(db):
    c = Case(folder_name="x", radicado_23_digitos="68001400902420260005500")
    db.add(c); db.commit()
    return c


def _proc(acts):
    return {"actuaciones": [{"fecha": f, "actuacion": t, "anotacion": n} for f, t, n in acts]}


def test_inserta_y_dedup(db):
    c = _case(db)
    p = _proc([("18/03/2026", "Auto Admite y Avoca Tutela", "avoca"),
               ("06/04/2026", "Sentencia de Primera Instancia de Tutela", "concede")])
    r = sync_case_actuaciones(db, c, p)
    assert r["added"] == 2
    # segunda pasada idéntica → 0 (dedup)
    assert sync_case_actuaciones(db, c, p)["added"] == 0
    rows = db.query(CaseActuacion).filter(CaseActuacion.case_id == c.id).all()
    assert len(rows) == 2
    assert all(r.source == SOURCE for r in rows)


def test_detecta_nuevas(db):
    c = _case(db)
    sync_case_actuaciones(db, c, _proc([("18/03/2026", "Auto Admite", "x")]))
    r = sync_case_actuaciones(db, c, _proc([
        ("18/03/2026", "Auto Admite", "x"),
        ("15/04/2026", "Auto de Impugnacion de Tutela", "impugna")]))
    assert r["added"] == 1
    assert r["nuevas"] == [{"fecha": "15/04/2026", "tipo": "Auto de Impugnacion de Tutela"}]


def test_no_pisa_bitacora_excel(db):
    c = _case(db)
    db.add(CaseActuacion(case_id=c.id, tipo_actuacion="TUTELA",
                         fecha_actuacion="01/01/2026", source="control_tutelas_xlsx"))
    db.commit()
    sync_case_actuaciones(db, c, _proc([("18/03/2026", "Auto Admite", "x")]))
    # la fila del Excel sigue ahí + la nueva CPNU
    srcs = {r.source for r in db.query(CaseActuacion).filter(CaseActuacion.case_id == c.id)}
    assert srcs == {"control_tutelas_xlsx", SOURCE}
