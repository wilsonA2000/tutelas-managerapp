"""Tests del refinamiento de necesita_revision (propuesta #6, 2026-05-25).

Regla validada: muchos juzgados municipales/promiscuos NO emiten el CUP de 23
dígitos, solo el rad corto ("2026-00083"). Un caso identificado por rad corto y
con >1 doc NO es un error accionable aunque le falte radicado_23_digitos. El flag
crudo `sin_radicado` se conserva (filtro UI), pero deja de sumar a necesita_revision.
"""
import types

import pytest

from backend.services import case_service as cs


def _stub(folder, rad23, n_docs, **kw):
    docs = [types.SimpleNamespace(verificacion="OK") for _ in range(n_docs)]
    base = dict(
        tipo_actuacion="TUTELA", documents=docs, accionante="JUAN PEREZ",
        folder_name=folder, radicado_23_digitos=rad23,
        incidente="NO", incidente_2="NO", incidente_3="NO",
        fecha_apertura_incidente="", fecha_apertura_incidente_2="",
        fecha_apertura_incidente_3="", impugnacion="NO", quien_impugno="",
        sentido_fallo_1st="NIEGA",
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _fix_completitud(monkeypatch):
    # Aísla la prueba de la lógica de completitud/extracción.
    monkeypatch.setattr(cs, "_get_case_completitud", lambda c: 90.0)
    monkeypatch.setattr(cs, "_case_extraido", lambda c, compl=None: True)


def test_short_rad_only_no_cuenta_como_revision():
    c = _stub("2026-00083 SONIA MARCELA PAEZ", None, 5)
    f = cs._case_review_flags(c)
    assert f["sin_radicado"] is True          # flag crudo se conserva (filtro UI)
    assert f["necesita_revision"] is False     # pero NO es accionable (rad corto + >1 doc)


def test_rad_corto_interno_gobernacion_tambien_cuenta_como_identificado():
    # El nº interno de la Gobernación ("2026-21107") también identifica el caso.
    c = _stub("2026-21107 FRANCY JOHANA SIERRA", None, 3)
    assert cs._case_review_flags(c)["necesita_revision"] is False


def test_sin_ningun_rad_si_es_revision():
    c = _stub("CARPETA SIN RADICADO ALGUNO", None, 5)
    f = cs._case_review_flags(c)
    assert f["sin_radicado"] is True
    assert f["necesita_revision"] is True      # no hay forma de identificarlo


def test_shell_con_rad_corto_pero_un_solo_doc_si_es_revision():
    c = _stub("2026-00083 X", None, 1)
    f = cs._case_review_flags(c)
    assert f["necesita_revision"] is True      # 1 doc = shell (pocos_docs)


def test_con_rad23_no_dispara_sin_radicado():
    c = _stub("2026-00083 X", "68001400900120260008300", 5)
    f = cs._case_review_flags(c)
    assert f["sin_radicado"] is False
    assert f["necesita_revision"] is False
