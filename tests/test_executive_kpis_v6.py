"""Tests 9.9: Executive KPIs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case
from backend.services.executive_kpis import (
    compute_compliance_rate, compute_response_times,
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


class TestCompliance:
    def test_vacio(self, db):
        r = compute_compliance_rate([])
        assert r["total_activos"] == 0
        assert r["compliance_rate"] == 0.0

    def test_todos_completo(self, db):
        cases = [_c(db, folder_name=f"A{i}", processing_status="COMPLETO") for i in range(5)]
        r = compute_compliance_rate(cases)
        assert r["compliance_rate"] == 1.0
        assert r["completo"] == 5

    def test_mixto(self, db):
        cases = [
            _c(db, folder_name="A", processing_status="COMPLETO"),
            _c(db, folder_name="B", processing_status="REVISION"),
            _c(db, folder_name="C", processing_status="PENDIENTE"),
            _c(db, folder_name="D", processing_status="DUPLICATE_MERGED"),  # no cuenta
        ]
        r = compute_compliance_rate(cases)
        assert r["total_activos"] == 3
        assert r["completo"] == 1
        assert r["compliance_rate"] == round(1 / 3, 3)


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
        cases = [
            _c(db, folder_name="A", abogado_responsable="Ana", estado_incidente="EN_SANCION"),
            _c(db, folder_name="B", abogado_responsable="Ana", estado_incidente="N/A"),
            _c(db, folder_name="C", abogado_responsable="Bob", estado_incidente="N/A"),
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
        _c(db, folder_name="A", processing_status="COMPLETO",
           fecha_ingreso="01/03/2026", fecha_respuesta="05/03/2026",
           sentido_fallo_1st="CONCEDE", ciudad="Bucaramanga",
           abogado_responsable="Test Abogado")
        payload = executive_dashboard(db)
        assert "summary" in payload
        assert "compliance" in payload
        assert "top_abogados" in payload
        assert "by_month" in payload
        assert "impugnacion" in payload
        import json
        json.dumps(payload)  # serializable
