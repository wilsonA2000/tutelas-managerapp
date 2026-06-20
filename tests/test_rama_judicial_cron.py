"""Guard 2026-06-20: el cron de sync Rama Judicial (Pendiente A) sincroniza solo
casos ACTIVOS con rad23 válido, emite alertas de novedad por actuaciones nuevas, y
ABORTA tras errores consecutivos (anti rate-limit CPNU). Cliente inyectado → sin red."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case
from backend.alerts.models import Alert
from backend.services.rama_judicial_cron import sync_active_cases

RAD_OK = "68001333300820230026700"  # 23 díg Santander, válido


class _FakeProceso:
    def __init__(self, payload):
        self._p = payload

    def to_dict(self):
        return self._p


def _noop(_s):  # reemplaza time.sleep
    return None


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add_all([
        Case(id=1, folder_name="2023-00267 ACTIVO", processing_status="COMPLETO",
             estado="ACTIVO", radicado_23_digitos=RAD_OK),
        Case(id=2, folder_name="2023-00099 INACTIVO", processing_status="COMPLETO",
             estado="INACTIVO", radicado_23_digitos="68001333300820230009900"),
        Case(id=3, folder_name="2023-00088 ACTIVO sin rad", processing_status="COMPLETO",
             estado="ACTIVO", radicado_23_digitos=None),
    ])
    s.commit()
    yield s
    s.close()


def test_solo_activos_con_rad_y_emite_alerta(db):
    proceso = {"encontrado": True, "actuaciones": [
        {"fecha": "01/06/2026", "actuacion": "Fallo Tutela", "anotacion": "concede"},
        {"fecha": "02/06/2026", "actuacion": "Notificación", "anotacion": ""},
    ]}
    res = sync_active_cases(db, client=lambda rad: _FakeProceso(proceso),
                            throttle=0, cooldown=0, sleep=_noop)
    # solo c1 califica (c2 inactivo, c3 sin rad23)
    assert res["candidatos"] == 1 and res["procesados"] == 1
    assert res["con_novedad"] == 1
    # 1 alerta (Fallo), la Notificación no alerta
    assert res["alertas"] == 1
    alerts = db.query(Alert).all()
    assert len(alerts) == 1 and alerts[0].case_id == 1


def test_aborta_tras_errores_consecutivos(db):
    # añadir más casos activos para tener candidatos suficientes
    for i in range(10, 15):
        db.add(Case(id=i, folder_name=f"c{i}", processing_status="COMPLETO",
                    estado="ACTIVO", radicado_23_digitos=f"680013333008202300{i:03d}00"))
    db.commit()

    def _boom(rad):
        raise RuntimeError("HTTP 429 rate limit")

    res = sync_active_cases(db, client=_boom, throttle=0, cooldown=0, sleep=_noop)
    assert res["abortado"] is True
    assert res["errores"] == 3  # corta en el 3er error consecutivo
    assert res["procesados"] == 0


def test_sin_candidatos_no_rompe(db):
    # marcar el único activo como inactivo → 0 candidatos
    db.query(Case).filter(Case.id == 1).first().estado = "INACTIVO"
    db.commit()
    res = sync_active_cases(db, client=lambda rad: _FakeProceso({"encontrado": True}),
                            throttle=0, cooldown=0, sleep=_noop)
    assert res["candidatos"] == 0 and res["procesados"] == 0 and res["alertas"] == 0
