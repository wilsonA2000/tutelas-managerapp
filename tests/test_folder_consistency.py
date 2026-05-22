"""Tests del detector de conflación cross-juzgado (backend/v9/folder_consistency.py).

Cubre las mejoras 2026-05-21 contra la conflación por rad corto compartido (c23/c129/c62)
y, sobre todo, casos ADVERSARIALES que intentan forzar el fallo / anticipan situaciones
futuras que aún no se han presentado:
- rad pegado a "_" o letras en el filename; rad como subcadena de un número más largo.
- OCR con separadores raros (espacios/puntos/guiones mezclados).
- citas de radicados AJENOS en el cuerpo (vinculaciones/jurisprudencia) que NO deben
  confundirse con el rad propio.
- EMPATE en el fallback de mayoría (rad23 NULL) → debe ser indeterminable, no adivinar.
- acumulación legítima (mismo juzgado, consecutivos -00066/-00067) → NO es conflación.
- escalamiento a 2da (-01 vs -00) y remisión por competencia → NO es conflación.
- entradas vacías / longitud inválida → robustez sin excepciones.
"""
import types

import pytest

from backend.v9 import folder_consistency as fc
from backend.v9.folder_consistency import (
    _own_rad, _is_reparto_doc, _expected_juzgado, _juzgado, _norm23,
    check_folder_consistency,
)

# rads reales de la sesión 2026-05-21
RAD_SIPRECOL = "68001333301420260003200"   # c23, Juz 14 Admin Bucaramanga
RAD_EMILI = "68679407100120260003200"      # c480, Juz 1 Penal Adolesc San Gil (mismo rad corto 00032)
RAD_FLORIDA = "68276418900320260013700"    # c170, Juz 3 Peq Causas Floridablanca
RAD_BUCARA = "68001418900320260012200"     # rad anterior de c170 (remitido por competencia)


# ───────────────────────── _norm23 / _RAD23 (parsing robusto) ──────────────────────
def test_norm23_solo_acepta_23_digitos():
    assert _norm23("68001-3333-014-2026-00032-00") == RAD_SIPRECOL
    assert _norm23("2026-00032") is None
    assert _norm23(None) is None
    assert _norm23("") is None


@pytest.mark.parametrize("longitud", ["6800133330142026000320", "680013333014202600032000"])
def test_norm23_rechaza_22_y_24_digitos(longitud):
    # OCR puede comer o duplicar un dígito → NO debe aceptarse como rad válido
    assert _norm23(longitud) is None


def test_own_rad_pegado_a_underscore_o_letras():
    # filenames reales usan "_" (carácter de palabra que rompía \b en la versión vieja)
    assert _own_rad("Fallo_680013333014-2026-00032-00.pdf", None) == RAD_SIPRECOL
    assert _own_rad("FALLO680013333014-2026-00032-00x.pdf", None) == RAD_SIPRECOL


def test_own_rad_no_matchea_subcadena_de_numero_mas_largo():
    # un número de 25 dígitos NO debe producir un "rad" de 23 cortando dígitos
    assert _own_rad("9680013333014202600032009.pdf", None) is None


def test_own_rad_ocr_separadores_mezclados():
    txt = "RADICADO: 68001 3333 014.2026-00032 00"
    assert _own_rad("x.pdf", txt) == RAD_SIPRECOL


def test_own_rad_ignora_citas_en_el_cuerpo():
    # el rad PROPIO está en el encabezado; una cita de OTRO rad aparece después → gana el propio
    txt = ("JUZGADO 14\nRADICADO: 680013333014-2026-00032-00\n... se vincula el proceso "
           "68679-4071-001-2026-00040-00 de otro despacho por conexidad ...")
    assert _own_rad("doc.pdf", txt) == RAD_SIPRECOL


def test_own_rad_vacio():
    assert _own_rad(None, None) is None
    assert _own_rad("", "") is None


# ───────────────────────── _is_reparto_doc (excluir competencia) ──────────────────
def test_is_reparto_doc_detecta_competencia():
    assert _is_reparto_doc("002AccionTutela.pdf",
                           "ACTA REPARTO N° 14279 ... REMITE ACCION DE TUTELA POR COMPETENCIA")
    assert _is_reparto_doc(None, "remite la acción por falta de competencia al juzgado")
    assert _is_reparto_doc(None, "ACTA DE REPARTO No 998")


def test_is_reparto_doc_no_se_dispara_con_sentencia_normal():
    assert not _is_reparto_doc("Sentencia.pdf", "PRIMERO: TUTELAR los derechos fundamentales...")
    assert not _is_reparto_doc("auto.pdf", "el despacho avoca conocimiento de la presente acción")


# ───────────────────────── _expected_juzgado (fallback rad23 NULL) ─────────────────
def test_expected_juzgado_usa_rad_del_caso():
    juz, src = _expected_juzgado(RAD_SIPRECOL, [])
    assert juz == _juzgado(RAD_SIPRECOL) and src == "case_rad23"


def test_expected_juzgado_fallback_mayoria_cuando_rad_null():
    docs = [RAD_FLORIDA, RAD_FLORIDA, RAD_BUCARA]  # 2 Floridablanca, 1 Bucaramanga
    juz, src = _expected_juzgado(None, docs)
    assert juz == _juzgado(RAD_FLORIDA) and src == "mayoria_docs"


def test_expected_juzgado_empate_es_indeterminable():
    # 2 vs 2: adivinar marcaría mal la mitad → debe abstenerse
    docs = [RAD_FLORIDA, RAD_FLORIDA, RAD_BUCARA, RAD_BUCARA]
    juz, src = _expected_juzgado(None, docs)
    assert juz is None and src == "indeterminable_empate"


def test_expected_juzgado_unico_doc_se_acepta():
    juz, src = _expected_juzgado(None, [RAD_BUCARA])
    assert juz == _juzgado(RAD_BUCARA) and src == "mayoria_docs"


def test_expected_juzgado_sin_docs_es_indeterminable():
    juz, src = _expected_juzgado(None, [])
    assert juz is None and src == "indeterminable"


# ───────────────────────── integración: check_folder_consistency ──────────────────
def _doc(did, filename=None, text=None, verif=None):
    return types.SimpleNamespace(
        id=did, filename=filename, extracted_text=text,
        verificacion=verif, verificacion_detalle=None,
    )


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows
    def filter(self, *a, **k):
        return self
    def first(self):
        return self.rows[0] if self.rows else None
    def all(self):
        return self.rows


class _FakeDB:
    """DB falsa mínima: devuelve el caso para query(Case) y los docs para query(Document)."""
    def __init__(self, case, docs):
        self._case, self._docs = case, docs
    def query(self, model):
        from backend.database.models import Case as C
        return _FakeQuery([self._case] if (model is C and self._case) else
                          ([] if model is C else self._docs))


def _case(cid=1, rad=None):
    return types.SimpleNamespace(id=cid, radicado_23_digitos=rad)


def test_integration_caso_limpio():
    db = _FakeDB(_case(rad=RAD_SIPRECOL),
                 [_doc(1, "RADICADO 680013333014-2026-00032-00.pdf"),
                  _doc(2, text="RADICADO: 680013333014-2026-00032-00")])
    r = check_folder_consistency(db, 1)
    assert r["clean"] and r["n_issues"] == 0


def test_integration_detecta_doc_de_otro_juzgado():
    db = _FakeDB(_case(rad=RAD_SIPRECOL),
                 [_doc(1, "Fallo_680013333014-2026-00032-00.pdf"),
                  _doc(2, "AutoSanGil_686794071001-2026-00032-00.pdf")])  # San Gil ≠ Bucaramanga
    r = check_folder_consistency(db, 1)
    assert not r["clean"]
    tipos = {i["tipo"] for i in r["issues"]}
    assert "CONFLACION" in tipos  # mismo rad corto 00032, juzgado distinto


def test_integration_no_marca_remision_por_competencia():
    # el doc tiene rad de otro juzgado PERO es un acta de reparto → misma tutela, no contaminación
    db = _FakeDB(_case(rad=RAD_FLORIDA),
                 [_doc(1, "Fallo_682764189003-2026-00137-00.pdf"),
                  _doc(2, "ActaReparto.pdf",
                       text="RADICADO: 680014189003-2026-00122-00  REMITE POR COMPETENCIA")])
    r = check_folder_consistency(db, 1)
    assert r["clean"], r["issues"]


def test_integration_no_marca_escalamiento_a_segunda():
    # -01 (2da instancia) vs -00 (1ra) del mismo rad corto pero juzgado superior → legítimo
    rad_2da = "68001310500120260003201"  # juzgado distinto, recurso -01
    db = _FakeDB(_case(rad=RAD_SIPRECOL),
                 [_doc(1, "Fallo1ra_680013333014-2026-00032-00.pdf"),
                  _doc(2, "Fallo2da_683013105001-2026-00032-01.pdf")])
    r = check_folder_consistency(db, 1)
    # el doc -01 no debe marcarse como conflación (es la 2da del mismo proceso)
    assert all(i.get("doc_rad") != rad_2da for i in r["issues"])


def test_integration_rad_null_usa_mayoria():
    # caso shell (rad23 NULL, como c129): identidad por mayoría; el doc ajeno se marca
    db = _FakeDB(_case(rad=None),
                 [_doc(1, "A_682764189003-2026-00137-00.pdf"),
                  _doc(2, "B_682764189003-2026-00137-00.pdf"),
                  _doc(3, "Ajeno_680014189003-2026-00122-00.pdf")])
    r = check_folder_consistency(db, 1)
    ajenos = [i for i in r["issues"] if i["tipo"] in ("CONFLACION", "RAD_AJENO")]
    assert len(ajenos) == 1 and ajenos[0]["doc_id"] == 3


def test_integration_rad_null_empate_no_marca_nada():
    # 2 vs 2 sin rad del caso → indeterminable → NO marcar nada (evita falsos positivos)
    db = _FakeDB(_case(rad=None),
                 [_doc(1, "A_682764189003-2026-00137-00.pdf"),
                  _doc(2, "B_682764189003-2026-00137-00.pdf"),
                  _doc(3, "C_680014189003-2026-00122-00.pdf"),
                  _doc(4, "D_680014189003-2026-00122-00.pdf")])
    r = check_folder_consistency(db, 1)
    assert r["clean"], r["issues"]


def test_integration_doc_ya_OK_no_se_marca():
    # decisión humana previa (verificacion=OK) gana sobre el detector
    db = _FakeDB(_case(rad=RAD_SIPRECOL),
                 [_doc(1, "Ajeno_686794071001-2026-00032-00.pdf", verif="OK")])
    r = check_folder_consistency(db, 1)
    assert r["clean"]


def test_integration_caso_inexistente_no_explota():
    db = _FakeDB(None, [])
    r = check_folder_consistency(db, 999)
    assert r["clean"] and "error" in r
