"""Regresión 2026-06-12 — caso real e2042 (impugnación de c516 cayó a c90):

1. `extract_juzgado_municipio` no entendía "SEÑOR JUEZ ... DE CIMITARRA" (solo
   "JUZGADO") → la desambiguación F2 por municipio nunca recibía el municipio.
2. `create_new_case` con rad corto compartido por VARIOS casos y correo sin rad23
   devolvía el PRIMER match a ciegas (el de id más bajo) → conflación.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case
from backend.email.case_resolver import extract_juzgado_municipio, match_by_rad_corto


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _c(db, folder, rad23, juzgado):
    c = Case(folder_name=folder, radicado_23_digitos=rad23, juzgado=juzgado)
    db.add(c); db.commit()
    return c


def test_juez_sin_juzgado_extrae_municipio():
    t = ("SEÑOR (a) JUEZ PRIMERO PENAL DEL CIRCUITO CON FUNCIONES DE "
         "CONOCIMIENTO DE CIMITARRA – SANTANDER")
    assert extract_juzgado_municipio(t) == "CIMITARRA"


def test_juzgado_clasico_sigue_funcionando():
    assert extract_juzgado_municipio("JUZGADO PROMISCUO MUNICIPAL DE GALAN") == "GALAN"


def test_rad_corto_ambiguo_desambigua_por_municipio(db):
    _c(db, "2026-00080 YENNIFER LARROTA", "68001400301720260008000",
       "JUZGADO DECIMOSEPTIMO CIVIL MUNICIPAL DE BUCARAMANGA")
    _c(db, "2026-00080 EDGAR GALVIS", "68001400301420260008000",
       "JUZGADO DECIMOCUARTO CIVIL MUNICIPAL DE BUCARAMANGA")
    target = _c(db, "2026-00080 LLAMISTH ORTIZ", "68190310400120260008000",
                "JUZGADO PRIMERO PENAL DEL CIRCUITO DE CIMITARRA")
    c, mth = match_by_rad_corto(db, "2026-00080", municipio="CIMITARRA",
                                accionante="", email_rad23="")
    assert c is not None and c.id == target.id
    assert mth == "rad_corto+municipio"


def test_create_new_case_no_adivina_en_ambiguo(db, tmp_path, monkeypatch):
    import backend.email.gmail_monitor as gm
    monkeypatch.setattr(gm, "BASE_DIR", tmp_path)
    _c(db, "2026-00099 PRIMERA PERSONA", "68001400301720260009900", "J17 BUCARAMANGA")
    _c(db, "2026-00099 SEGUNDA PERSONA", "68190310400120260009900", "J1 CIMITARRA")
    # correo SIN rad23: no debe devolver ninguno de los dos ni crear uno nuevo
    case = gm.create_new_case(db, {"radicado_corto": "2026-00099", "radicado_23": ""}, "")
    assert case is None


def test_create_new_case_unico_si_dedup(db, tmp_path, monkeypatch):
    import backend.email.gmail_monitor as gm
    monkeypatch.setattr(gm, "BASE_DIR", tmp_path)
    unico = _c(db, "2026-00777 UNICA PERSONA", "68001400301720260077700", "J17")
    case = gm.create_new_case(db, {"radicado_corto": "2026-00777", "radicado_23": ""}, "")
    assert case is not None and case.id == unico.id
