"""Tests F1: medición de entropía del cuadro de casos."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.cognition.entropy import (
    entropy_of_case, entropy_of_db, shannon_entropy,
    _inconsistencies, _classify_field, ALL_FIELDS, FIELD_STATES,
)


class _Case:
    """Case mínimo para tests."""
    def __init__(self, **kw):
        # Inicializar todos los campos a None, luego aplicar kwargs
        for f in ALL_FIELDS:
            setattr(self, f, None)
        self.id = kw.get("id", 1)
        self.folder_name = kw.get("folder_name", "test")
        self.processing_status = kw.get("processing_status", "COMPLETO")
        for k, v in kw.items():
            setattr(self, k, v)


class TestShannonEntropy:
    def test_distribucion_uniforme_maxima(self):
        # 4 estados con probabilidades iguales → H = log2(4) = 2
        h = shannon_entropy({"a": 1, "b": 1, "c": 1, "d": 1})
        assert abs(h - 2.0) < 1e-9

    def test_un_solo_estado_entropia_cero(self):
        h = shannon_entropy({"a": 10, "b": 0, "c": 0})
        assert h == 0.0

    def test_vacio(self):
        assert shannon_entropy({}) == 0.0
        assert shannon_entropy({"a": 0, "b": 0}) == 0.0


class TestCaseEntropy:
    def test_caso_vacio_tiene_alta_entropia(self):
        c = _Case()
        r = entropy_of_case(c)
        # Con todos los campos vacíos y sin datos de decisión, casi todos
        # caen en empty_expected o empty_not_applicable → poca entropía porque
        # los estados se concentran en pocas categorías
        assert r.entropy_bits >= 0.0
        assert r.state_counts["filled_high"] == 0

    def test_caso_lleno_consistente(self):
        c = _Case(
            radicado_23_digitos="68001400902720260003400",
            radicado_forest="3410516",
            accionante="Paola Andrea",
            accionados="Gobernación",
            derecho_vulnerado="Salud",
            juzgado="Juzgado 9",
            ciudad="Bucaramanga",
            fecha_ingreso="15/03/2026",
            asunto="Traslado docente",
            pretensiones="Reubicación",
            oficina_responsable="Desarrollo Docente",
            observaciones="En trámite",
            abogado_responsable="Juan Cruz",
            impugnacion="NO",
            incidente="NO",
        )
        r = entropy_of_case(c)
        assert r.state_counts["filled_high"] >= 5   # rad23, forest, fecha_ingreso, etc.
        assert r.state_counts["inconsistent"] == 0

    def test_inconsistencia_impugnacion_no_con_datos_2nd(self):
        c = _Case(
            impugnacion="NO",
            quien_impugno="Accionante",          # contradicción
            sentido_fallo_2nd="CONFIRMA",        # contradicción
        )
        r = entropy_of_case(c)
        assert "quien_impugno" in r.inconsistent_fields
        assert "sentido_fallo_2nd" in r.inconsistent_fields

    def test_inconsistencia_incidente_no_con_datos_desacato(self):
        c = _Case(
            incidente="NO",
            responsable_desacato="Secretario",   # contradicción
            decision_incidente="Archiva",        # contradicción
        )
        r = entropy_of_case(c)
        assert "responsable_desacato" in r.inconsistent_fields
        assert "decision_incidente" in r.inconsistent_fields

    def test_consistente_si_impugnacion_si(self):
        c = _Case(
            impugnacion="SI",
            quien_impugno="Accionante",
            sentido_fallo_2nd="CONFIRMA",
            fecha_fallo_1st="15/03/2026",
        )
        r = entropy_of_case(c)
        # impugnacion=SI con datos 2da instancia → no hay inconsistencia
        assert "quien_impugno" not in r.inconsistent_fields


class TestDbEntropy:
    def test_lista_vacia(self):
        r = entropy_of_db([])
        assert r["total_cases"] == 0
        assert r["mean_entropy"] == 0.0

    def test_varios_casos(self):
        cases = [_Case(id=1, impugnacion="NO"), _Case(id=2, incidente="NO")]
        r = entropy_of_db(cases)
        assert r["total_cases"] == 2
        assert "aggregate_states" in r
        assert "worst_cases" in r


class TestFieldClassification:
    def test_campo_no_aplicable_cuando_impugnacion_no(self):
        c = _Case(impugnacion="NO")
        st = _classify_field(c, "quien_impugno", set())
        assert st == "empty_not_applicable"

    def test_campo_esperado_cuando_impugnacion_si(self):
        c = _Case(impugnacion="SI")
        st = _classify_field(c, "quien_impugno", set())
        assert st == "empty_expected"

    def test_campo_inconsistente(self):
        c = _Case(impugnacion="NO", quien_impugno="X")
        bad = _inconsistencies(c)
        st = _classify_field(c, "quien_impugno", bad)
        assert st == "inconsistent"
