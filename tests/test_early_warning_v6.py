"""Tests 9.4: Early Warning system (semáforo de riesgo)."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case
from backend.alerts.early_warning import (
    score_case, run_early_warning, _parse_date, _days_ago,
    LEVEL_RED, LEVEL_YELLOW, LEVEL_GREEN, LEVEL_NA,
    INCIDENT_DAYS_TO_RED, INCIDENT_DAYS_TO_YELLOW,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    s = S()
    yield s
    s.close()


def _mk(db, **kw):
    c = Case(
        folder_name=kw.get("folder_name", "F"),
        processing_status=kw.get("processing_status", "COMPLETO"),
        origen=kw.get("origen", "TUTELA"),
        estado_incidente=kw.get("estado_incidente", "N/A"),
        sentido_fallo_1st=kw.get("sentido_fallo_1st"),
        fecha_fallo_1st=kw.get("fecha_fallo_1st"),
        fecha_respuesta=kw.get("fecha_respuesta"),
        fecha_apertura_incidente=kw.get("fecha_apertura_incidente"),
        abogado_responsable=kw.get("abogado_responsable", ""),
        entropy_score=kw.get("entropy_score"),
    )
    db.add(c); db.commit(); return c


NOW = datetime(2026, 4, 23)


class TestParseDate:
    def test_fechas_validas(self):
        assert _parse_date("15/03/2026") == datetime(2026, 3, 15)
        assert _parse_date("3-4-2026") == datetime(2026, 4, 3)

    def test_fechas_invalidas(self):
        assert _parse_date(None) is None
        assert _parse_date("") is None
        assert _parse_date("sin fecha") is None
        assert _parse_date("32/13/2026") is None

    def test_days_ago(self):
        assert _days_ago("23/04/2026", NOW) == 0
        assert _days_ago("13/04/2026", NOW) == 10
        assert _days_ago(None, NOW) is None


class TestScoring:
    def test_en_sancion_siempre_rojo(self, db):
        c = _mk(db, estado_incidente="EN_SANCION")
        r = score_case(c, now=NOW)
        assert r.level == LEVEL_RED
        assert r.score == 1.0
        assert any("SANCIÓN" in s for s in r.reasons)

    def test_incidente_activo_muchos_dias_rojo(self, db):
        c = _mk(db, estado_incidente="ACTIVO",
                fecha_apertura_incidente="01/03/2026")  # 53 días antes
        r = score_case(c, now=NOW)
        assert r.level == LEVEL_RED

    def test_incidente_activo_medio_amarillo(self, db):
        c = _mk(db, estado_incidente="ACTIVO",
                fecha_apertura_incidente="11/04/2026")  # 12 días antes
        r = score_case(c, now=NOW)
        assert r.level == LEVEL_YELLOW

    def test_incidente_reciente_verde(self, db):
        c = _mk(db, estado_incidente="ACTIVO",
                fecha_apertura_incidente="20/04/2026")  # 3 días
        r = score_case(c, now=NOW)
        # score 0.25 → VERDE en realidad (threshold yellow = 0.40)
        assert r.level == LEVEL_GREEN

    def test_fallo_concede_sin_respuesta_rojo(self, db):
        c = _mk(db,
                sentido_fallo_1st="CONCEDE el amparo",
                fecha_fallo_1st="10/04/2026",  # 13 días
                fecha_respuesta=None)
        r = score_case(c, now=NOW)
        assert r.level == LEVEL_RED

    def test_fallo_concede_con_respuesta_verde(self, db):
        c = _mk(db,
                sentido_fallo_1st="CONCEDE",
                fecha_fallo_1st="01/04/2026",
                fecha_respuesta="05/04/2026")
        r = score_case(c, now=NOW)
        assert r.level == LEVEL_GREEN

    def test_entropia_alta_genera_amarillo(self, db):
        c = _mk(db, entropy_score=2.3)
        r = score_case(c, now=NOW)
        assert r.level in (LEVEL_YELLOW,)
        assert any("Entropía" in s for s in r.reasons)

    def test_incidente_huerfano_amarillo(self, db):
        c = _mk(db, origen="INCIDENTE_HUERFANO")
        r = score_case(c, now=NOW)
        assert r.level == LEVEL_YELLOW
        assert any("huérfano" in s.lower() for s in r.reasons)

    def test_revision_suma_pero_queda_verde_sin_otras_alertas(self, db):
        c = _mk(db, processing_status="REVISION")
        r = score_case(c, now=NOW)
        # Solo REVISION aporta 0.35, bajo el threshold de AMARILLO (0.40)
        assert r.level == LEVEL_GREEN

    def test_duplicate_merged_es_na(self, db):
        c = _mk(db, processing_status="DUPLICATE_MERGED")
        r = score_case(c, now=NOW)
        assert r.level == LEVEL_NA


class TestRunEarlyWarning:
    def test_summary_basico(self, db):
        _mk(db, folder_name="A", estado_incidente="EN_SANCION")
        _mk(db, folder_name="B", estado_incidente="ACTIVO", fecha_apertura_incidente="11/04/2026")
        _mk(db, folder_name="C", origen="INCIDENTE_HUERFANO")
        _mk(db, folder_name="D", estado_incidente="N/A")

        summary = run_early_warning(db, now=NOW)
        assert summary.total_cases_evaluated == 4
        assert summary.by_level[LEVEL_RED] == 1
        assert summary.by_level[LEVEL_YELLOW] >= 1

    def test_rojos_ordenados_por_score_desc(self, db):
        _mk(db, folder_name="A", estado_incidente="EN_SANCION")
        _mk(db, folder_name="B", sentido_fallo_1st="CONCEDE",
            fecha_fallo_1st="10/04/2026")  # rojo pero <1.0

        summary = run_early_warning(db, now=NOW)
        if len(summary.red_cases) >= 2:
            assert summary.red_cases[0].score >= summary.red_cases[1].score

    def test_to_dict_serializable(self, db):
        _mk(db, folder_name="Zzz", estado_incidente="EN_SANCION")
        summary = run_early_warning(db, now=NOW)
        d = summary.to_dict()
        import json
        json.dumps(d)  # no explota
        assert "by_level" in d
        assert "red" in d
