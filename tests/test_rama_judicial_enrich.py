"""Tests de la etapa v9 rama_judicial_enrich (Fase B) — CPNU mockeado, sin red."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case
from backend.v9 import rama_judicial_enrich as enrich
from backend.v9.types import ExtractedFields, FieldSource
from backend.services import rama_judicial_client as rj


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _case(db, rad="68001400902420260005500"):
    c = Case(folder_name="x", radicado_23_digitos=rad)
    db.add(c); db.commit()
    return c


def _proc(**kw):
    p = rj.ProcesoCPNU(rad23="68001400902420260005500", encontrado=True)
    p.juzgado = kw.get("juzgado", "JUZGADO 024 PENAL MUNICIPAL DE BUCARAMANGA")
    p.fecha_radicacion = kw.get("fecha", "18/03/2026")
    return p


def test_flag_off_no_op(db, monkeypatch):
    monkeypatch.setenv("RAMA_JUDICIAL_ENABLED", "false")
    f = ExtractedFields()
    r = enrich.run(db, _case(db), f)
    assert "skipped" in r
    assert not f.values["juzgado"]   # no tocó nada


def test_flag_on_force_setea(db, monkeypatch):
    monkeypatch.setenv("RAMA_JUDICIAL_ENABLED", "true")
    monkeypatch.setattr(enrich, "_get_or_sync", lambda d, c, r: _proc().to_dict())
    f = ExtractedFields()
    f.set("juzgado", "JUZGADO VIEJO REGEX", FieldSource.REGEX)   # ya había valor regex
    r = enrich.run(db, _case(db), f)
    assert r["found"] is True
    assert "juzgado" in r["applied"] and "fecha_ingreso" in r["applied"]
    # force-set pisó el regex en `fields` con source API
    assert f.values["juzgado"] == "JUZGADO 024 PENAL MUNICIPAL DE BUCARAMANGA"
    assert f.sources["juzgado"] == FieldSource.API_RAMA_JUDICIAL
    assert f.values["fecha_ingreso"] == "18/03/2026"


def test_rad_invalido(db, monkeypatch):
    monkeypatch.setenv("RAMA_JUDICIAL_ENABLED", "true")
    r = enrich.run(db, _case(db, rad="123"), ExtractedFields())
    assert "skipped" in r


def test_no_encontrado(db, monkeypatch):
    monkeypatch.setenv("RAMA_JUDICIAL_ENABLED", "true")
    monkeypatch.setattr(enrich, "_get_or_sync",
                        lambda d, c, r: {"encontrado": False, "error": "no_encontrado"})
    r = enrich.run(db, _case(db), ExtractedFields())
    assert r["found"] is False
