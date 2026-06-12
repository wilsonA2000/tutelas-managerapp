"""Tests 9.9: Executive KPIs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case
from backend.services.executive_kpis import (
    compute_estado_procesal, compute_response_times,
    compute_fallos_distribution, compute_by_month,
    compute_top_municipios, compute_top_oficinas, compute_top_abogados,
    compute_top_accionantes_recurrentes, compute_impugnacion_rate,
    executive_dashboard, _parse, _ym,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()
    yield s
    s.close()


def _c(db, **kw):
    c = Case(
        folder_name=kw.pop("folder_name", f"F-{id(kw)}"),
        processing_status=kw.pop("processing_status", "COMPLETO"),
        **kw,
    )
    db.add(c); db.commit(); return c


class TestParse:
    def test_fechas(self):
        from datetime import datetime
        assert _parse("15/03/2026") == datetime(2026, 3, 15)
        assert _parse(None) is None
        assert _parse("") is None
        assert _parse("foo") is None

    def test_ym(self):
        from datetime import datetime
        assert _ym(datetime(2026, 3, 15)) == "2026-03"
        assert _ym(datetime(2026, 12, 1)) == "2026-12"


class TestEstadoProcesal:
    # P19: la autoridad es cases.estado (curado), no processing_status (legacy).
    def test_vacio(self, db):
        r = compute_estado_procesal([])
        assert r["total"] == 0
        assert r["pct_resueltas"] == 0.0

    def test_todos_inactivos(self, db):
        cases = [_c(db, folder_name=f"A{i}", estado="INACTIVO") for i in range(5)]
        r = compute_estado_procesal(cases)
        assert r["pct_resueltas"] == 1.0
        assert r["inactivos"] == 5

    def test_mixto(self, db):
        cases = [
            _c(db, folder_name="A", estado="ACTIVO"),
            _c(db, folder_name="B", estado="ACTIVO"),
            _c(db, folder_name="C", estado="INACTIVO"),
            _c(db, folder_name="D", estado=None),  # cuenta como sin_estado
        ]
        r = compute_estado_procesal(cases)
        assert r["total"] == 4
        assert r["activos"] == 2
        assert r["inactivos"] == 1
        assert r["sin_estado"] == 1
        assert r["pct_resueltas"] == 0.25


class TestResponseTimes:
    def test_sin_datos(self, db):
        r = compute_response_times([])
        assert r["avg_days"] is None
        assert r["sample_size"] == 0

    def test_con_fechas(self, db):
        cases = [
            _c(db, folder_name="A", fecha_ingreso="01/03/2026", fecha_respuesta="05/03/2026"),  # 4 días
            _c(db, folder_name="B", fecha_ingreso="01/03/2026", fecha_respuesta="11/03/2026"),  # 10 días
        ]
        r = compute_response_times(cases)
        assert r["avg_days"] == 7.0
        assert r["sample_size"] == 2

    def test_sin_respuesta_con_fallo(self, db):
        cases = [
            _c(db, folder_name="A", fecha_ingreso="01/03/2026",
               fecha_respuesta=None, fecha_fallo_1st="10/03/2026"),
        ]
        r = compute_response_times(cases)
        assert r["sin_respuesta_total"] == 1
        assert r["sin_respuesta_con_fallo"] == 1


class TestFallos:
    def test_normaliza_sentidos(self, db):
        cases = [
            _c(db, folder_name="A", sentido_fallo_1st="CONCEDE el amparo"),
            _c(db, folder_name="B", sentido_fallo_1st="AMPARA parcialmente"),
            _c(db, folder_name="C", sentido_fallo_1st="NIEGA"),
            _c(db, folder_name="D", sentido_fallo_1st="IMPROCEDENTE"),
            _c(db, folder_name="E", sentido_fallo_1st=None),  # no cuenta
        ]
        r = compute_fallos_distribution(cases)
        d = {x["sentido"]: x["count"] for x in r}
        assert d["CONCEDE"] == 2  # CONCEDE + AMPARA
        assert d["NIEGA"] == 1
        assert d["IMPROCEDENTE"] == 1


class TestByMonth:
    def test_ordena_por_mes(self, db):
        cases = [
            _c(db, folder_name="A", fecha_ingreso="15/03/2026"),
            _c(db, folder_name="B", fecha_ingreso="20/03/2026"),
            _c(db, folder_name="C", fecha_ingreso="01/02/2026"),
        ]
        r = compute_by_month(cases)
        assert len(r) == 2
        assert r[0]["month"] == "2026-02"
        assert r[1]["month"] == "2026-03"
        assert r[1]["count"] == 2


class TestTopRankings:
    def test_top_municipios(self, db):
        cases = [
            _c(db, folder_name=f"A{i}", ciudad="Bucaramanga") for i in range(3)
        ] + [
            _c(db, folder_name="B", ciudad="San Gil"),
        ]
        r = compute_top_municipios(cases)
        assert r[0]["municipio"] == "Bucaramanga"
        assert r[0]["count"] == 3

    def test_top_abogados_con_incidente(self, db):
        # P19: incidente activo = incidente=SI + decision viva + caso ACTIVO.
        cases = [
            _c(db, folder_name="A", abogado_responsable="Ana", estado="ACTIVO",
               incidente="SI", decision_incidente="EN_TRAMITE"),
            _c(db, folder_name="B", abogado_responsable="Ana", estado="INACTIVO"),
            _c(db, folder_name="C", abogado_responsable="Bob", estado="ACTIVO"),
        ]
        r = compute_top_abogados(cases)
        ana = next(a for a in r if a["abogado"] == "Ana")
        assert ana["total_casos"] == 2
        assert ana["casos_activos_incidente"] == 1

    def test_accionantes_recurrentes_filtra_unicos(self, db):
        cases = [
            _c(db, folder_name=f"A{i}", accionante="Juan Pérez García") for i in range(3)
        ] + [
            _c(db, folder_name="B", accionante="María López"),  # única
        ]
        r = compute_top_accionantes_recurrentes(cases)
        assert len(r) == 1
        assert r[0]["accionante"] == "JUAN PÉREZ GARCÍA"
        assert r[0]["procesos"] == 3


class TestImpugnacion:
    def test_rates(self, db):
        cases = [
            _c(db, folder_name="A", sentido_fallo_1st="CONCEDE", impugnacion="SI"),
            _c(db, folder_name="B", sentido_fallo_1st="CONCEDE", impugnacion="NO"),
            _c(db, folder_name="C", sentido_fallo_1st="NIEGA", impugnacion="NO"),
            _c(db, folder_name="D", sentido_fallo_1st=None),  # no cuenta
        ]
        r = compute_impugnacion_rate(cases)
        assert r["total_con_fallo"] == 3
        assert r["total_impugnadas"] == 1
        assert r["concedidas"] == 2
        assert r["concedidas_impugnadas"] == 1


class TestExecutiveIntegration:
    def test_payload_completo(self, db):
        _c(db, folder_name="A", estado="ACTIVO",
           fecha_ingreso="01/03/2026", fecha_respuesta="05/03/2026",
           sentido_fallo_1st="CONCEDE", ciudad="Bucaramanga",
           abogado_responsable="Test Abogado")
        # processing_status NULL no debe descontar el caso (bug del filtro viejo)
        _c(db, folder_name="B", processing_status=None, estado="INACTIVO")
        payload = executive_dashboard(db)
        assert "summary" in payload
        assert "estado_procesal" in payload
        assert "incidentes_decision" in payload
        assert payload["summary"]["total_cases"] == 2
        assert "top_abogados" in payload
        assert "by_month" in payload
        assert "impugnacion" in payload
        import json
        json.dumps(payload)  # serializable
