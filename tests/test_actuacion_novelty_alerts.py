"""Guard 2026-06-20: emit_actuacion_novelty_alerts emite una Alert por cada
actuación CPNU NUEVA significativa (fallo/sentencia/sanción/desacato) y nada por
las triviales (notificaciones, oficios). Dedup por título; fechas distintas →
alertas distintas. Cierra la Fase C (hook de novedad de Rama Judicial)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case
from backend.alerts.models import Alert  # registra la tabla en Base
from backend.alerts.detector import emit_actuacion_novelty_alerts


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Case(id=1, folder_name="2026-00010 TEST", processing_status="COMPLETO"))
    session.commit()
    yield session
    session.close()


def _case(db):
    return db.query(Case).filter(Case.id == 1).first()


def _alerts(db):
    return db.query(Alert).all()


def test_fallo_emite_alerta_high(db):
    n = emit_actuacion_novelty_alerts(db, _case(db), [{"fecha": "01/06/2026", "tipo": "Fallo Tutela"}])
    assert n == 1
    a = _alerts(db)[0]
    assert a.alert_type == "NOVEDAD_RAMA_JUDICIAL" and a.severity == "HIGH"
    assert a.case_id == 1 and "01/06/2026" in a.title


def test_sancion_y_desacato_high(db):
    n = emit_actuacion_novelty_alerts(db, _case(db), [
        {"fecha": "02/06/2026", "tipo": "Sanción por desacato Art. 52"},
        {"fecha": "03/06/2026", "tipo": "Apertura incidente de desacato"},
    ])
    assert n == 2
    assert all(a.severity == "HIGH" for a in _alerts(db))


def test_trivial_no_emite(db):
    n = emit_actuacion_novelty_alerts(db, _case(db), [
        {"fecha": "04/06/2026", "tipo": "Notificación por estado"},
        {"fecha": "05/06/2026", "tipo": "Oficio remisorio"},
    ])
    assert n == 0
    assert _alerts(db) == []


def test_dedup_misma_actuacion(db):
    act = [{"fecha": "06/06/2026", "tipo": "Sentencia de segunda instancia"}]
    assert emit_actuacion_novelty_alerts(db, _case(db), act) == 1
    assert emit_actuacion_novelty_alerts(db, _case(db), act) == 0  # re-sync no duplica
    assert len(_alerts(db)) == 1


def test_mismo_tipo_distinta_fecha_son_distintas(db):
    assert emit_actuacion_novelty_alerts(db, _case(db), [{"fecha": "07/06/2026", "tipo": "Fallo"}]) == 1
    assert emit_actuacion_novelty_alerts(db, _case(db), [{"fecha": "20/06/2026", "tipo": "Fallo"}]) == 1
    assert len(_alerts(db)) == 2


def test_lista_vacia_no_rompe(db):
    assert emit_actuacion_novelty_alerts(db, _case(db), []) == 0
    assert emit_actuacion_novelty_alerts(db, _case(db), None) == 0
