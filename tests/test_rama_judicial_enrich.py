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


def _case(db, rad="68001400902420260005500", impugnacion=None):
    c = Case(folder_name="x", radicado_23_digitos=rad, impugnacion=impugnacion)
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
    # force-set pisó el regex en `fields` con source API; el numeral CPNU (024) se
    # normaliza a la forma curada (VEINTICUATRO) antes de persistir.
    assert f.values["juzgado"] == "JUZGADO VEINTICUATRO PENAL MUNICIPAL DE BUCARAMANGA"
    assert f.sources["juzgado"] == FieldSource.API_RAMA_JUDICIAL
    assert f.values["fecha_ingreso"] == "18/03/2026"


def test_no_impugnado_pisa_juzgado_1ra(db, monkeypatch):
    """impugnacion=NO → el despacho CPNU = 1ra instancia → va a `juzgado` (autoritativo)."""
    monkeypatch.setenv("RAMA_JUDICIAL_ENABLED", "true")
    monkeypatch.setattr(enrich, "_get_or_sync",
                        lambda d, c, r: _proc(juzgado="JUZGADO 016 CIVIL MUNICIPAL DE BUCARAMANGA").to_dict())
    f = ExtractedFields()
    r = enrich.run(db, _case(db, impugnacion="NO"), f)
    assert "juzgado" in r["applied"]
    assert f.values["juzgado"] == "JUZGADO DIECISÉIS CIVIL MUNICIPAL DE BUCARAMANGA"
    assert f.sources["juzgado"] == FieldSource.API_RAMA_JUDICIAL
    assert not f.values["juzgado_2nd"]   # no se tocó la 2da


def test_impugnado_no_pisa_1ra_va_a_juzgado_2nd(db, monkeypatch):
    """impugnacion=SI → el despacho CPNU es 2DA instancia → va a `juzgado_2nd`,
    NUNCA a `juzgado` (se conserva el de 1ra curado). Decisión Wilson 2026-06-20."""
    monkeypatch.setenv("RAMA_JUDICIAL_ENABLED", "true")
    monkeypatch.setattr(enrich, "_get_or_sync",
                        lambda d, c, r: _proc(juzgado="JUZGADO 009 CIVIL CIRCUITO DE BUCARAMANGA").to_dict())
    f = ExtractedFields()
    f.set("juzgado", "JUZGADO PROMISCUO MUNICIPAL DE ZAPATOCA", FieldSource.REGEX)  # 1ra curada
    r = enrich.run(db, _case(db, impugnacion="SI"), f)
    assert "juzgado_2nd" in r["applied"]
    assert "juzgado" not in r["applied"]
    # la 1ra instancia curada NO fue pisada
    assert f.values["juzgado"] == "JUZGADO PROMISCUO MUNICIPAL DE ZAPATOCA"
    assert f.sources["juzgado"] == FieldSource.REGEX
    # la 2da instancia se llenó con el despacho CPNU normalizado
    assert f.values["juzgado_2nd"] == "JUZGADO NOVENO CIVIL CIRCUITO DE BUCARAMANGA"
    assert f.sources["juzgado_2nd"] == FieldSource.API_RAMA_JUDICIAL


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
