"""Tests del auditor automatizado: 1 caso sintetico por regla."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import audit_cases as ac


def make_case(**kw):
    """Crea un Case-like sin tocar la DB."""
    defaults = dict(
        id=1, folder_name="2026-00001 TEST", tipo_actuacion="TUTELA",
        radicado_23_digitos="68001310500120260000100", radicado_forest="2826001",
        accionante="JUAN PEREZ", abogado_responsable="ANGELICA YADIRA BARROSO SARMIENTO",
        abogado_canonical="ANGELICA YADIRA BARROSO SARMIENTO",
        impugnacion="NO", quien_impugno=None,
        sentido_fallo_1st=None, fecha_fallo_1st=None,
        sentido_fallo_2nd=None, juzgado_2nd=None, fecha_fallo_2nd=None,
        juzgado="JUZGADO PROMISCUO MUNICIPAL DE BETULIA",
        fecha_ingreso="01/02/2026",
        incidente=None, fecha_apertura_incidente=None, responsable_desacato=None,
        dependencia_canonical=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_R1_impugnacion_no_pero_fallo_2nd_lleno():
    c = make_case(impugnacion="NO", sentido_fallo_2nd="CONFIRMA",
                  juzgado_2nd="TRIBUNAL", fecha_fallo_2nd="01/03/2026")
    f = ac.rule_R1(c)
    assert len(f) == 3
    assert {x.field for x in f} == {"sentido_fallo_2nd", "juzgado_2nd", "fecha_fallo_2nd"}
    assert all(x.severity == "ERROR" for x in f)


def test_R1_impugnacion_no_consistente():
    c = make_case(impugnacion="NO")
    assert ac.rule_R1(c) == []


def test_R2_fallo_2nd_sin_juzgado_o_fecha():
    c = make_case(impugnacion="SI", sentido_fallo_2nd="REVOCA", juzgado_2nd=None, fecha_fallo_2nd=None)
    f = ac.rule_R2(c)
    fields = {x.field for x in f}
    assert "juzgado_2nd" in fields and "fecha_fallo_2nd" in fields


def test_R3_enum_invalido():
    c = make_case(sentido_fallo_1st="ALGO_RARO")
    f = ac.rule_R3(c)
    assert any(x.field == "sentido_fallo_1st" for x in f)


def test_R3_enum_valido():
    c = make_case(sentido_fallo_1st="CONCEDE", sentido_fallo_2nd="CONFIRMA")
    assert ac.rule_R3(c) == []


def test_R4_incidente_si_sin_fecha_ni_responsable():
    c = make_case(incidente="SI", fecha_apertura_incidente=None, responsable_desacato=None)
    f = ac.rule_R4(c)
    fields = {x.field for x in f}
    assert "fecha_apertura_incidente" in fields and "responsable_desacato" in fields


def test_R5_radicado_truncado():
    c = make_case(radicado_23_digitos="123456789012345")  # 15 digits
    f = ac.rule_R5(c)
    assert len(f) == 1 and f[0].field == "radicado_23_digitos"


def test_R5_radicado_valido():
    c = make_case(radicado_23_digitos="68001310500120260000100")
    assert ac.rule_R5(c) == []


def test_R6_fechas_desordenadas():
    c = make_case(fecha_ingreso="15/03/2026", fecha_fallo_1st="01/02/2026")  # fallo antes de ingreso
    f = ac.rule_R6(c)
    assert any(x.rule == "R6" for x in f)


def test_R6_fechas_ordenadas():
    c = make_case(fecha_ingreso="01/02/2026", fecha_fallo_1st="15/03/2026", fecha_fallo_2nd="01/05/2026")
    assert ac.rule_R6(c) == []


def test_R7_tutela_sin_radicados():
    c = make_case(tipo_actuacion="TUTELA", radicado_23_digitos=None, radicado_forest=None)
    f = ac.rule_R7(c)
    assert len(f) == 1 and f[0].rule == "R7"


def test_R7_incidente_sin_radicado_no_falla():
    c = make_case(tipo_actuacion="INCIDENTE", radicado_23_digitos=None, radicado_forest=None)
    assert ac.rule_R7(c) == []


def test_R8_impugnacion_si_sin_quien_impugno():
    c = make_case(impugnacion="SI", quien_impugno=None)
    f = ac.rule_R8(c)
    assert len(f) == 1 and f[0].field == "quien_impugno"


def test_R9_juzgados_iguales():
    c = make_case(juzgado="JUZGADO X", juzgado_2nd="JUZGADO X")
    f = ac.rule_R9(c)
    assert len(f) == 1


def test_R9_juzgados_distintos():
    c = make_case(juzgado="JUZGADO X", juzgado_2nd="TRIBUNAL Y")
    assert ac.rule_R9(c) == []


def test_R10_canonical_vacio_pero_resoluble():
    c = make_case(abogado_responsable="ANGELICA YADIRA BARROSO SARMIENTO", abogado_canonical=None)
    f = ac.rule_R10(c)
    assert any(x.severity == "WARN" and "sugerido" in x.evidence for x in f)


def test_R10_firmante_operativo():
    c = make_case(abogado_responsable="Jorge Enrique Gualdrón Martínez / Abogado externo",
                  abogado_canonical=None)
    f = ac.rule_R10(c)
    assert all(x.severity == "INFO" for x in f)


def test_R11_accionante_vacio():
    c = make_case(accionante=None)
    f = ac.rule_R11(c)
    assert len(f) == 1 and f[0].field == "accionante"


def test_R11_accionante_None_string():
    c = make_case(accionante="None")
    assert len(ac.rule_R11(c)) == 1


def test_R12_disenso_excel_vs_db():
    c = make_case(abogado_canonical="VICTOR ALFONSO COLMENARES NIÑO")
    actuaciones = [SimpleNamespace(abogado_canonical="ANGELICA YADIRA BARROSO SARMIENTO",
                                    dependencia_canonical=None)]
    f = ac.rule_R12(c, actuaciones)
    assert any(x.field == "abogado_canonical" for x in f)


def test_audit_case_runs_all_rules():
    c = make_case(impugnacion="NO", sentido_fallo_2nd="CONFIRMA",
                  accionante=None, radicado_23_digitos="123")
    findings = ac.audit_case(c, [])
    rules = {f.rule for f in findings}
    assert "R1" in rules and "R5" in rules and "R11" in rules
