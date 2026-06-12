"""Fase 5 — tests para los KPIs que estaban SIN cobertura:
pipeline_funnel, fallo_2nd_distribution, incidentes_decision, compliance_plazos.
(P19: by_origen fue reemplazado por incidentes_decision — campos curados.)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case
from backend.services.executive_kpis import (
    compute_incidentes_decision, compute_fallo_2nd_distribution,
    compute_pipeline_funnel, compute_compliance_plazos,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _c(db, **kw):
    c = Case(folder_name=kw.pop("folder_name", f"F-{id(kw)}"),
             processing_status=kw.pop("processing_status", "COMPLETO"), **kw)
    db.add(c); db.commit()
    return c


def test_incidentes_decision(db):
    _c(db, incidente="SI", decision_incidente="EN_TRAMITE")
    _c(db, incidente="SI", decision_incidente="EN_TRAMITE")
    _c(db, incidente="SI", decision_incidente="SANCIONA")
    _c(db, incidente="SI", decision_incidente=None)   # abierto sin decidir
    _c(db, incidente="NO", decision_incidente=None)   # sin incidente → no cuenta
    r = compute_incidentes_decision(db.query(Case).all())
    assert r["EN_TRAMITE"] == 2 and r["SANCIONA"] == 1 and r["SIN_DECISION"] == 1
    assert sum(r.values()) == 4


def test_fallo_2nd_distribution(db):
    _c(db, sentido_fallo_2nd="CONFIRMA")
    _c(db, sentido_fallo_2nd="REVOCA PARCIALMENTE")
    _c(db, sentido_fallo_2nd="PENDIENTE")  # excluido
    r = compute_fallo_2nd_distribution(db.query(Case).all())
    kinds = {d["sentido"]: d["count"] for d in r}
    assert kinds.get("CONFIRMA") == 1 and kinds.get("REVOCA") == 1
    assert sum(d["count"] for d in r) == 2
    assert all(0 <= d["pct"] <= 100 for d in r)


def test_pipeline_funnel(db):
    _c(db, sentido_fallo_1st="CONCEDE", impugnacion="SI",
       sentido_fallo_2nd="CONFIRMA", incidente="SI")
    _c(db, sentido_fallo_1st="NIEGA")
    _c(db)  # sin fallo
    r = compute_pipeline_funnel(db.query(Case).all())
    s = {d["stage"]: d["count"] for d in r}
    assert s["TUTELA"] == 3 and s["FALLO_1ST"] == 2
    assert s["IMPUGNADO"] == 1 and s["FALLO_2ND"] == 1 and s["INCIDENTE"] == 1
    assert all(d["count"] <= s["TUTELA"] for d in r)  # cada nivel ≤ total


def test_compliance_plazos(db):
    # P19: lee estado/decision_incidente curados, no estado_incidente legacy.
    _c(db, sentido_fallo_1st="CONCEDE", fecha_fallo_1st="01/01/2020",
       estado="ACTIVO")  # pendiente (>10 días)
    _c(db, sentido_fallo_1st="CONCEDE", fecha_fallo_1st="01/01/2020",
       estado="INACTIVO")  # cerrada
    _c(db, sentido_fallo_1st="CONCEDE", fecha_fallo_1st="01/01/2020",
       estado="ACTIVO", decision_incidente="SANCIONA")  # en sanción
    _c(db, sentido_fallo_1st="NIEGA", fecha_fallo_1st="01/01/2020",
       estado="ACTIVO")  # no CONCEDE → ignorado
    r = compute_compliance_plazos(db.query(Case).all())
    assert r["concedidas_pendientes_cumplimiento"] == 1
    assert r["concedidas_cerradas"] == 1
    assert r["en_sancion"] == 1
    assert len(r["top_pendientes"]) == 1
