"""Tests del resolver de acumulaciones con DB (crear hermanos, vincular, enrutar).

DB SQLite en memoria, aislada (no toca la DB compartida del conftest).
"""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case, Document
from backend.email.acumulacion_resolver import (
    apply_acumulacion_note,
    plan_acumulacion,
    resolve_acumulacion,
)

JUZ = "683444089001"  # Juzgado 01 Promiscuo Municipal de Hato

SENT = {
    "45": ("SENTENCIA maria.pdf", "RADICADO: 2025-00045-00\nACCIONANTE: MARIA PAULA MENDEZ RAMIREZ\nNotificación"),
    "46": ("SENTENCIA gilma.pdf", "RADICADO: 2025-00046-00\nACCIONANTE: GILMA LUCIA HERNANDEZ BERNAL\nNotificación"),
    "47": ("SENTENCIA liliana.pdf", "RADICADO: 2025-00047-00\nACCIONANTE: LILIANA PATRICIA CALA CALA\nNotificación"),
}
ENUM_DOC = ("Email_acumulados.md",
            "RESPUESTA REQUERIMIENTO RADICADOS 2025-00045, 2025-00046 y 00047 ACUMULADOS")


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


def _mk_case(db, rad23=None, accionante=None, folder=None, juzgado="JUZGADO 01 PROMISCUO MUNICIPAL DE HATO"):
    c = Case(radicado_23_digitos=rad23, accionante=accionante,
             folder_name=folder or (accionante or "caso"), juzgado=juzgado, ciudad="HATO")
    db.add(c)
    db.flush()
    return c


def _add_doc(db, case_id, filename, text):
    d = Document(case_id=case_id, filename=filename, extracted_text=text,
                 file_path=f"/tmp/{filename}")
    db.add(d)
    db.flush()
    return d


def test_crea_hermano_faltante_y_vincula(db):
    """Bucket con las 3 sentencias + enumeración: crea Liliana, vincula los 3."""
    rector = _mk_case(db, rad23=f"{JUZ}20250004500", accionante="MARIA PAULA MENDEZ RAMIREZ",
                      folder="2025-00045 MARIA PAULA MENDEZ RAMIREZ")
    gilma = _mk_case(db, rad23=None, accionante="GILMA LUCIA HERNANDEZ BERNAL",
                     folder="2025-00046 GILMA LUCIA HERNANDEZ BERNAL")
    for k in ("45", "46", "47"):
        _add_doc(db, rector.id, *SENT[k])
    _add_doc(db, rector.id, *ENUM_DOC)
    db.commit()

    plan = resolve_acumulacion(db, rector, apply=True)
    assert plan.is_acumulacion
    assert plan.rector_rad == "2025-00045"

    # Liliana fue creada
    lili = db.query(Case).filter(Case.accionante == "LILIANA PATRICIA CALA CALA").first()
    assert lili is not None
    assert lili.radicado_23_digitos == f"{JUZ}20250004700"
    assert lili.tipo_acumulacion == "ACUMULADO"
    assert lili.acumulado_a_case_id == rector.id

    # Rector marcado, Gilma vinculada + rad23 backfilled
    db.refresh(rector); db.refresh(gilma)
    assert rector.tipo_acumulacion == "RECTOR"
    assert gilma.tipo_acumulacion == "ACUMULADO"
    assert gilma.radicado_23_digitos == f"{JUZ}20250004600"  # backfill

    # Sentencia de Liliana y de Gilma enrutadas fuera del rector
    lili_docs = db.query(Document).filter(Document.case_id == lili.id).all()
    assert any("liliana" in d.filename.lower() for d in lili_docs)
    gilma_docs = db.query(Document).filter(Document.case_id == gilma.id).all()
    assert any("gilma" in d.filename.lower() for d in gilma_docs)


def test_idempotente(db):
    """Correr dos veces no duplica casos ni cambia vínculos."""
    rector = _mk_case(db, rad23=f"{JUZ}20250004500", accionante="MARIA PAULA MENDEZ RAMIREZ")
    for k in ("45", "46", "47"):
        _add_doc(db, rector.id, *SENT[k])
    _add_doc(db, rector.id, *ENUM_DOC)
    db.commit()

    resolve_acumulacion(db, rector, apply=True)
    n1 = db.query(Case).count()
    resolve_acumulacion(db, rector, apply=True)
    n2 = db.query(Case).count()
    assert n1 == n2 == 3


def test_bucket_sucio_no_crea_basura(db):
    """Un OFICIO ajeno (otra tutela) y radicados malformados NO generan casos."""
    rector = _mk_case(db, rad23=f"{JUZ}20250004500", accionante="MARIA PAULA MENDEZ RAMIREZ")
    for k in ("45", "47"):
        _add_doc(db, rector.id, *SENT[k])
    _add_doc(db, rector.id, ENUM_DOC[0], "RADICADOS 2025-00045 y 00047 ACUMULADOS")
    # Doc ajeno: segunda instancia de OTRA tutela (rad 2025-00200), mal archivado
    _add_doc(db, rector.id, "OFICIO_708_2da_instancia_2025_00200.pdf",
             "RADICADO: 2025-00200-01\nACCIONANTE: PERSONA AJENA DISTINTA\nSegunda instancia")
    # Ruido malformado
    _add_doc(db, rector.id, "ref_2025-000.md", "referencia 2025-00000 y 2025-00030 sueltos")
    db.commit()

    plan = plan_acumulacion(db, rector)
    rads = {it.rad_corto for it in plan.items}
    assert rads == {"2025-00045", "2025-00047"}  # ni 00200 ni 00000 ni 00030
    resolve_acumulacion(db, rector, apply=True)
    # No se creó caso para la persona ajena
    assert db.query(Case).filter(Case.accionante == "PERSONA AJENA DISTINTA").first() is None
    assert db.query(Case).count() == 2  # rector + Liliana


def test_nota_observaciones_idempotente_y_no_pisa(db):
    """La nota [ACUMULACIÓN CONJUNTA] lista a los miembros, no pisa prosa previa
    y no se duplica al re-aplicar."""
    rector = _mk_case(db, rad23=f"{JUZ}20250004500", accionante="MARIA PAULA MENDEZ RAMIREZ")
    for k in ("45", "46", "47"):
        _add_doc(db, rector.id, *SENT[k])
    _add_doc(db, rector.id, *ENUM_DOC)
    db.commit()
    resolve_acumulacion(db, rector, apply=True)

    lili = db.query(Case).filter(Case.accionante == "LILIANA PATRICIA CALA CALA").first()
    db.refresh(lili)
    # la nota existe y lista a los 3 con el rector marcado
    assert lili.observaciones.startswith("[ACUMULACIÓN CONJUNTA]")
    assert "MARIA PAULA MENDEZ RAMIREZ (RECTOR)" in lili.observaciones
    assert "GILMA" not in lili.observaciones or "LILIANA PATRICIA CALA CALA" in lili.observaciones

    # agregar prosa manual y re-aplicar: no se pisa, no se duplica el marcador
    lili.observaciones = lili.observaciones + "\n\nNota manual del operador."
    db.commit()
    apply_acumulacion_note(db, lili)
    db.commit()
    db.refresh(lili)
    assert lili.observaciones.count("[ACUMULACIÓN CONJUNTA]") == 1
    assert "Nota manual del operador." in lili.observaciones


def test_caso_simple_no_dispara(db):
    """Caso normal de una sola tutela: el resolver no hace nada."""
    c = _mk_case(db, rad23=f"{JUZ}20260010000", accionante="JUAN PEREZ")
    _add_doc(db, c.id, "fallo.pdf", "RADICADO: 2026-00100-00\nACCIONANTE: JUAN PEREZ\nNotificación sentencia")
    db.commit()
    plan = resolve_acumulacion(db, c, apply=True)
    assert not plan.is_acumulacion
    assert db.query(Case).count() == 1
