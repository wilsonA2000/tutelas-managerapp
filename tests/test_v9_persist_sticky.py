"""Tests para `backend/v9/persist.py` — política sticky de identificadores.

Regresión 2026-05-15: v9 pisaba `radicado_23_digitos` del case con un rad ajeno
capturado en un doc anexo de antecedentes (ej. Case #421 DILSA — el rad correcto
era 11001020300020260042900 de la Corte Suprema, pero v9 lo pisó con
68081318400320250026100 de una tutela anterior contra el Juzgado de Barranca
que figuraba en los anexos). Fix: campos identificadores (`radicado_23_digitos`,
`radicado_forest`) son sticky y nunca se sobreescriben una vez establecidos.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case
from backend.v9.persist import persist, STICKY_FIELDS
from backend.v9.types import ExtractedFields, FieldSource


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _make_case(db, rad: str | None = None, forest: str | None = None, **kw) -> Case:
    c = Case(
        folder_name=kw.pop("folder_name", "2026-00001 PRUEBA"),
        radicado_23_digitos=rad,
        radicado_forest=forest,
        processing_status="PENDIENTE",
        **kw,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _fields_with(**kw) -> ExtractedFields:
    """Crea ExtractedFields con los valores dados (source=REGEX)."""
    f = ExtractedFields()
    for k, v in kw.items():
        f.set(k, v, FieldSource.REGEX)
    return f


def test_sticky_fields_constant():
    """Lista cerrada de campos sticky — cambios futuros requieren revisar tests."""
    assert "radicado_23_digitos" in STICKY_FIELDS
    assert "radicado_forest" in STICKY_FIELDS


def test_rad23_se_escribe_si_case_no_tenia(db):
    """Si el case no tiene rad, v9 SÍ puede escribirlo (primera vez)."""
    c = _make_case(db, rad=None)
    f = _fields_with(radicado_23_digitos="68001400900120260000100")
    r = persist(db, c.id, f, dry_run=False)
    assert r["changes"].get("radicado_23_digitos") is not None
    db.refresh(c)
    assert c.radicado_23_digitos == "68001400900120260000100"


def test_rad23_no_se_pisa_aunque_v9_proponga_otro(db):
    """REGRESIÓN: case ya con rad establecido NO debe pisarse aunque v9 vea
    otro rad en algún doc anexo."""
    c = _make_case(db, rad="11001020300020260042900")  # Corte Suprema (correcto)
    f = _fields_with(radicado_23_digitos="68081318400320250026100")  # rad ajeno
    r = persist(db, c.id, f, dry_run=False)
    # No debe entrar a cambios
    assert "radicado_23_digitos" not in r["changes"]
    # Debe figurar como conflicto sticky
    conflicts = r["sticky_conflicts"]
    assert any(x["field"] == "radicado_23_digitos" for x in conflicts)
    # DB intacto
    db.refresh(c)
    assert c.radicado_23_digitos == "11001020300020260042900"


def test_rad23_no_se_pisa_aunque_ya_estuviera_en_prev_sources(db):
    """Edge case: v9 había escrito el rad antes (queda en prev_sources). Una
    re-corrida con un rad distinto NO debe pisar (es sticky regardless)."""
    c = _make_case(db, rad="11001020300020260042900")
    # Simular tracking previo donde v9 ya había escrito ese rad
    c.field_confidences_json = (
        '{"v9_sources": {"radicado_23_digitos": "regex"}}'
    )
    db.commit()
    f = _fields_with(radicado_23_digitos="68081318400320250026100")
    r = persist(db, c.id, f, dry_run=False)
    assert "radicado_23_digitos" not in r["changes"]
    db.refresh(c)
    assert c.radicado_23_digitos == "11001020300020260042900"


def test_forest_no_se_pisa(db):
    """`radicado_forest` también es sticky."""
    c = _make_case(db, rad="68001400900120260000100", forest="20260000123")
    f = _fields_with(radicado_forest="20260009999")
    r = persist(db, c.id, f, dry_run=False)
    assert "radicado_forest" not in r["changes"]
    db.refresh(c)
    assert c.radicado_forest == "20260000123"


def test_no_sticky_field_si_se_pisa_normalmente(db):
    """Confirma que el guard sticky es específico — campos no-sticky siguen su
    política normal (no pisar si current existe sin prev_sources)."""
    c = _make_case(db, rad="68001400900120260000100", accionante="JUAN PEREZ")
    f = _fields_with(accionante="MARIA LOPEZ")
    r = persist(db, c.id, f, dry_run=False)
    # accionante NO es sticky pero tampoco se pisa porque current existe sin prev_sources
    assert "accionante" not in r["changes"]
    db.refresh(c)
    assert c.accionante == "JUAN PEREZ"


def test_sticky_no_genera_conflict_si_valor_es_el_mismo(db):
    """Si v9 propone el MISMO rad que ya tiene el case, NO es conflicto."""
    rad = "11001020300020260042900"
    c = _make_case(db, rad=rad)
    f = _fields_with(radicado_23_digitos=rad)
    r = persist(db, c.id, f, dry_run=False)
    assert r["sticky_conflicts"] == []
    assert "radicado_23_digitos" not in r["changes"]


# ── Incidente flag upgrade NO→SI (2026-06-17) ────────────────────────────────
# El flag `incidente='NO'` es un DEFAULT, no un hecho curado. Cuando nuevos docs
# revelan un desacato, debe poder hacer upgrade NO→SI aunque ya esté poblado
# (nunca SI→NO sin intervención manual). Sin esto quedaba incidente='NO' con
# decision_incidente poblado → contradicción que rompía la derivación de estado
# (c506/c18/c205).

def test_incidente_upgrade_no_a_si(db):
    """Case con incidente='NO' (default) → v9 detecta desacato → upgrade a 'SI'."""
    c = _make_case(db, incidente="NO")
    f = _fields_with(incidente="SI", decision_incidente="EN_TRAMITE")
    r = persist(db, c.id, f, dry_run=False)
    assert r["changes"].get("incidente", {}).get("new") == "SI"
    db.refresh(c)
    assert c.incidente == "SI"
    assert c.decision_incidente == "EN_TRAMITE"  # ya no queda la contradicción


def test_incidente_no_se_degrada_si_a_no(db):
    """SI→NO NO se permite (fill-only/manual): un re-extract sin señal no borra
    un incidente ya registrado."""
    c = _make_case(db, incidente="SI")
    f = _fields_with(incidente="NO")
    r = persist(db, c.id, f, dry_run=False)
    assert "incidente" not in r["changes"]
    db.refresh(c)
    assert c.incidente == "SI"


# ── API CPNU autoritativa en estructurales (Fase B, 2026-06-18) ──────────────
# juzgado/fecha_ingreso con source=API_RAMA_JUDICIAL pisan valor NO-manual;
# respetan MANUAL; fecha_ingreso con guard de coherencia (no posterior a fallo).

def _fields_api(**kw):
    f = ExtractedFields()
    for k, v in kw.items():
        f.values[k] = v
        f.sources[k] = FieldSource.API_RAMA_JUDICIAL
    return f


def test_api_pisa_juzgado_no_manual(db):
    c = _make_case(db, juzgado="JUZGADO REGEX MALO")
    f = _fields_api(juzgado="JUZGADO 024 PENAL MUNICIPAL DE BUCARAMANGA")
    r = persist(db, c.id, f, dry_run=False)
    assert r["changes"].get("juzgado", {}).get("new") == "JUZGADO 024 PENAL MUNICIPAL DE BUCARAMANGA"
    db.refresh(c)
    assert c.juzgado == "JUZGADO 024 PENAL MUNICIPAL DE BUCARAMANGA"


def test_api_no_pisa_juzgado_manual(db):
    c = _make_case(db, juzgado="JUZGADO CURADO A MANO")
    c.field_confidences_json = '{"v9_sources": {"juzgado": "manual"}}'
    db.commit()
    f = _fields_api(juzgado="JUZGADO API")
    r = persist(db, c.id, f, dry_run=False)
    assert "juzgado" not in r["changes"]
    db.refresh(c)
    assert c.juzgado == "JUZGADO CURADO A MANO"


def test_api_fecha_ingreso_guard_coherencia(db):
    # fecha API (19/05) POSTERIOR al fallo 1ra (13/03) → NO se aplica (rad de etapa posterior)
    c = _make_case(db, fecha_ingreso="01/03/2026", fecha_fallo_1st="13/03/2026")
    f = _fields_api(fecha_ingreso="19/05/2026")
    r = persist(db, c.id, f, dry_run=False)
    assert "fecha_ingreso" not in r["changes"]
    db.refresh(c)
    assert c.fecha_ingreso == "01/03/2026"


def test_api_fecha_ingreso_coherente_si_pisa(db):
    # fecha API (09/02) ANTERIOR al fallo (13/03) → coherente → pisa
    c = _make_case(db, fecha_ingreso="10/02/2026", fecha_fallo_1st="13/03/2026")
    f = _fields_api(fecha_ingreso="09/02/2026")
    r = persist(db, c.id, f, dry_run=False)
    assert r["changes"].get("fecha_ingreso", {}).get("new") == "09/02/2026"
    db.refresh(c)
    assert c.fecha_ingreso == "09/02/2026"
