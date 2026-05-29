"""Fix #11 (2026-05-28): guard cross-juzgado en match_by_rad_corto.

Reproduce las conflaciones de la ingesta del 2026-05-28: una tutela NUEVA cuyo
consecutivo (rad_corto) colisiona con el de un caso existente de OTRO juzgado. El
resolver F2 NO debe pegarla al caso existente cuando el correo trae su propio rad23.

DB SQLite en memoria, aislada.
"""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case
from backend.email.case_resolver import match_by_rad_corto


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _mk(db, rad23, accionante, rad_corto, juzgado="JUZGADO X", ciudad="X"):
    c = Case(radicado_23_digitos=rad23, accionante=accionante,
             folder_name=f"{rad_corto} {accionante}", juzgado=juzgado, ciudad=ciudad)
    db.add(c); db.flush()
    return c


def test_unique_rad_corto_distinto_juzgado_se_bloquea(db):
    """El caso de NANCY (Puerto Parra, juz 685734089001) es el ÚNICO con 2026-00038.
    Llega un AUTO ADMITE de GLADYS en San Joaquín (juz 686824089001), mismo consecutivo.
    NO debe pegarse a NANCY."""
    _mk(db, "685734089001202600038", "NANCY PAOLA MARTINEZ", "2026-00038",
        juzgado="JUZGADO 01 PROMISCUO MUNICIPAL DE PUERTO PARRA", ciudad="PUERTO PARRA")
    case, method = match_by_rad_corto(
        db, "2026-00038", accionante="GLADYS CONSUELO CARRENO BLANCO",
        email_rad23="686824089001202600038")
    assert case is None
    assert method == "rad_corto_cross_juzgado_blocked"


def test_unique_rad_corto_mismo_juzgado_si_matchea(db):
    """Mismo juzgado + mismo consecutivo = mismo expediente → sí asigna."""
    c = _mk(db, "685734089001202600038", "NANCY PAOLA MARTINEZ", "2026-00038")
    case, method = match_by_rad_corto(
        db, "2026-00038", email_rad23="685734089001202600038")
    assert case is c
    assert method == "rad_corto_unique"


def test_sin_email_rad23_comportamiento_legacy(db):
    """Sin rad23 del correo (respuesta SED que solo trae rad_corto) → unique como antes."""
    c = _mk(db, "685734089001202600038", "NANCY PAOLA MARTINEZ", "2026-00038")
    case, method = match_by_rad_corto(db, "2026-00038")
    assert case is c
    assert method == "rad_corto_unique"


def test_shell_sin_rad23_no_bloquea(db):
    """Un shell (rad23 NULL) con el mismo rad_corto sigue siendo adoptable (no bloquea)."""
    c = _mk(db, None, "PENDIENTE", "2026-00038")
    case, method = match_by_rad_corto(
        db, "2026-00038", email_rad23="686824089001202600038")
    assert case is c
    assert method == "rad_corto_unique"


def test_multi_caso_filtra_por_juzgado_del_email(db):
    """Dos casos homónimos (2026-00080) en juzgados distintos. El correo trae el rad23
    de Cimitarra → debe filtrar al de Cimitarra, no caer en ambigüedad."""
    _mk(db, "680014003017202600080", "YENNIFER LARROTA", "2026-00080",
        juzgado="JUZGADO 17 CIVIL MUNICIPAL DE BUCARAMANGA", ciudad="BUCARAMANGA")
    cim = _mk(db, "681903104001202600080", "LLAMISTH ORTIZ", "2026-00080",
              juzgado="JUZGADO PRIMERO PENAL DEL CIRCUITO DE CIMITARRA", ciudad="CIMITARRA")
    case, method = match_by_rad_corto(
        db, "2026-00080", email_rad23="681903104001202600080")
    assert case is cim
    assert method == "rad_corto_unique"  # tras filtrar quedó uno solo


def test_multi_caso_ambos_distinto_juzgado_bloquea(db):
    """Tutela NUEVA de un tercer juzgado (Cimitarra) cuyo consecutivo colisiona con DOS
    casos existentes de otros juzgados → ninguno compatible → bloquea."""
    _mk(db, "680014003017202600080", "YENNIFER LARROTA", "2026-00080",
        juzgado="JUZGADO 17 CIVIL MUNICIPAL DE BUCARAMANGA", ciudad="BUCARAMANGA")
    _mk(db, "680013109001202600080", "EDGAR GALVIS", "2026-00080",
        juzgado="JUZGADO 09 CIVIL MUNICIPAL DE BUCARAMANGA", ciudad="BUCARAMANGA")
    case, method = match_by_rad_corto(
        db, "2026-00080", email_rad23="681903104001202600080")
    assert case is None
    assert method == "rad_corto_cross_juzgado_blocked"
