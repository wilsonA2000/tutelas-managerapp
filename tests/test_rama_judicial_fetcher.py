"""Tests del fetcher de documentos CPNU (Fase D) — sin red, con CPNU mockeado."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case
from backend.services import rama_judicial_client as rj
from backend.services import rama_judicial_fetcher as rjf


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def test_safe_name():
    assert rjf._safe_name("18/03/2026", "Sentencia.pdf") == "RJ_18032026_Sentencia.pdf"
    assert rjf._safe_name(None, "Auto") == "RJ_Auto.pdf"          # añade .pdf
    assert rjf._safe_name("16/02/2026", "a/b:c.docx") == "RJ_16022026_a_b_c.docx"


def test_dry_run_no_escribe(db, tmp_path, monkeypatch):
    folder = tmp_path / "2026-00051 PRUEBA"
    folder.mkdir()
    c = Case(folder_name=folder.name, folder_path=str(folder),
             radicado_23_digitos="68081400300220260005100")
    db.add(c); db.commit()

    proc = rj.ProcesoCPNU(rad23="68081400300220260005100", encontrado=True, id_proceso=99)
    proc.actuaciones = [rj.Actuacion(fecha="16/02/2026", actuacion="Sentencia",
                                     anotacion=None, con_documentos=True, id_reg_actuacion=111)]
    monkeypatch.setattr(rjf.rj, "consultar_proceso", lambda *a, **k: proc)
    monkeypatch.setattr(rjf.rj, "documentos_actuacion",
                        lambda idreg, s: [{"idRegDocumento": 222, "nombre": "12SENTENCIA"}])

    r = rjf.fetch_case_documents(db, c.id, dry_run=True, throttle=0)
    assert r["estado"] == "OK" and r["found"] is True
    assert r["n_actuaciones_con_doc"] == 1
    assert r["descargados"] == 1            # contabiliza, pero…
    assert not list(folder.glob("RJ_*"))   # …NO escribió nada en disco (dry-run)


def test_rad_invalido(db, tmp_path):
    c = Case(folder_name="x", folder_path=str(tmp_path), radicado_23_digitos="123")
    db.add(c); db.commit()
    assert rjf.fetch_case_documents(db, c.id, dry_run=True)["estado"] == "RAD_INVALIDO"
