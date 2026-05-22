"""Tests del detector de conflación cross-juzgado (backend/v9/folder_consistency.py).

Cubre las mejoras 2026-05-21 contra la conflación por rad corto compartido:
- _own_rad: rad propio del doc desde filename o encabezado "RADICADO:".
- _is_reparto_doc: excluir remisiones por competencia (falso positivo c170).
- _expected_juzgado: fallback por juzgado mayoritario cuando el caso tiene rad23 NULL
  (punto ciego que dejó pasar c129).
"""
from backend.v9.folder_consistency import (
    _own_rad, _is_reparto_doc, _expected_juzgado, _juzgado, _norm23,
)

# rads reales de la sesión 2026-05-21
RAD_SIPRECOL = "68001333301420260003200"   # c23, Juz 14 Admin Bucaramanga
RAD_EMILI = "68679407100120260003200"      # c480, Juz 1 Penal Adolesc San Gil (mismo rad corto 00032)
RAD_FLORIDA = "68276418900320260013700"    # c170, Juz 3 Peq Causas Floridablanca
RAD_BUCARA = "68001418900320260012200"     # rad anterior de c170 (remitido por competencia)


def test_norm23_solo_acepta_23_digitos():
    assert _norm23("68001-3333-014-2026-00032-00") == "68001333301420260003200"
    assert _norm23("2026-00032") is None
    assert _norm23(None) is None


def test_own_rad_desde_filename():
    # rad como token (precedido por separador o inicio): matchea
    assert _own_rad("680013333014-2026-00032-00 Fallo.pdf", None) == RAD_SIPRECOL
    assert _own_rad("Fallo 680013333014-2026-00032-00.pdf", None) == RAD_SIPRECOL
    assert _own_rad("SentenciaTutela.pdf", None) is None  # solo rad corto/nada → None


def test_own_rad_desde_encabezado():
    txt = "JUZGADO 14 ADMINISTRATIVO\nRADICADO: 680013333014-2026-00032-00\nPROCESO: TUTELA"
    assert _own_rad("doc.pdf", txt) == RAD_SIPRECOL


def test_is_reparto_doc_detecta_competencia():
    # el caso real de c170: acta de reparto que remite por competencia
    assert _is_reparto_doc("002AccionTutela.pdf",
                           "ACTA REPARTO N° 14279 ... REMITE ACCION DE TUTELA POR COMPETENCIA")
    assert _is_reparto_doc(None, "remite la acción por falta de competencia al juzgado")
    assert not _is_reparto_doc("Sentencia.pdf", "PRIMERO: TUTELAR los derechos...")


def test_expected_juzgado_usa_rad_del_caso():
    juz, src = _expected_juzgado(RAD_SIPRECOL, [])
    assert juz == _juzgado(RAD_SIPRECOL) and src == "case_rad23"


def test_expected_juzgado_fallback_mayoria_cuando_rad_null():
    # caso con rad23 NULL (como c129) → identidad por juzgado mayoritario de los docs
    docs = [RAD_FLORIDA, RAD_FLORIDA, RAD_BUCARA]  # 2 Floridablanca, 1 Bucaramanga
    juz, src = _expected_juzgado(None, docs)
    assert juz == _juzgado(RAD_FLORIDA) and src == "mayoria_docs"


def test_expected_juzgado_indeterminable_sin_consenso():
    # rad23 NULL y un solo doc con rad ajeno → no se puede decidir identidad
    juz, src = _expected_juzgado(None, [RAD_BUCARA])
    assert juz == _juzgado(RAD_BUCARA)  # único → se acepta
    juz2, src2 = _expected_juzgado(None, [])
    assert juz2 is None and src2 == "indeterminable"
