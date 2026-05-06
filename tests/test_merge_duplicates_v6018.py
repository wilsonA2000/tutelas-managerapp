"""Tests para v6.0.18 — merge_duplicate_cases.

Cubre:
  - Caso simple: principal + dup con docs distintos → merge consolida
  - Coalescing: campos NULL en principal se rellenan desde dup
  - Idempotencia: re-corrida con dup ya MERGED no muta
  - Dry-run: no muta DB
"""
from __future__ import annotations

import pytest
import tempfile
from pathlib import Path
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case, Document, Email, AuditLog
from backend.services.cleanup_actions import merge_duplicate_cases


@pytest.fixture
def tmpdir_path():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _mk_case(db, tmpdir, name="TEST", **kwargs) -> Case:
    folder = tmpdir / name
    folder.mkdir(exist_ok=True)
    defaults = dict(
        folder_name=name,
        folder_path=str(folder),
        accionante="TEST ACCIONANTE",
        radicado_23_digitos=None,
        processing_status="COMPLETO",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    defaults.update(kwargs)
    c = Case(**defaults)
    db.add(c)
    db.commit()
    return c


def _mk_doc(db, case, filename="test.pdf", verificacion="OK") -> Document:
    """Crea Document + archivo físico real en el folder del case."""
    file_path = Path(case.folder_path) / filename
    file_path.write_text("contenido test")
    d = Document(
        case_id=case.id, filename=filename, file_path=str(file_path),
        verificacion=verificacion, extracted_text="texto",
    )
    db.add(d)
    db.commit()
    return d


def test_merge_simple_case(db, tmpdir_path):
    principal = _mk_case(db, tmpdir_path, name="PRINCIPAL", radicado_23_digitos="68001-2026-00060-00")
    dup = _mk_case(db, tmpdir_path, name="DUP_C", radicado_23_digitos=None)

    _mk_doc(db, dup, filename="doc1.pdf")
    _mk_doc(db, dup, filename="doc2.pdf")
    em = Email(case_id=dup.id, message_id="abc", subject="test")
    db.add(em); db.commit()

    result = merge_duplicate_cases(db, [(principal.id, dup.id)], dry_run=False)
    assert result["merged"] == 1
    assert result["errors"] == 0

    p_docs = db.query(Document).filter(Document.case_id == principal.id).count()
    d_docs = db.query(Document).filter(Document.case_id == dup.id).count()
    assert p_docs == 2
    assert d_docs == 0

    p_emails = db.query(Email).filter(Email.case_id == principal.id).count()
    assert p_emails == 1

    db.refresh(dup)
    assert dup.processing_status == "DUPLICATE_MERGED"
    assert "MERGED_INTO_CASE" in dup.folder_path


def test_dry_run_does_not_mutate(db, tmpdir_path):
    principal = _mk_case(db, tmpdir_path, name="P")
    dup = _mk_case(db, tmpdir_path, name="D")
    _mk_doc(db, dup, "a.pdf")

    result = merge_duplicate_cases(db, [(principal.id, dup.id)], dry_run=True)
    assert result["dry_run"] is True
    assert result["merged"] == 1

    db.refresh(dup)
    assert dup.processing_status == "COMPLETO"
    assert db.query(Document).filter(Document.case_id == dup.id).count() == 1


def test_coalescing_null_fields(db, tmpdir_path):
    principal = _mk_case(db, tmpdir_path, name="P",
                          radicado_23_digitos=None, juzgado=None, ciudad="Bucaramanga")
    dup = _mk_case(db, tmpdir_path, name="D",
                    radicado_23_digitos="68001-2026-00060-00",
                    juzgado="Juzgado Promiscuo Test",
                    ciudad="Otra ciudad")

    merge_duplicate_cases(db, [(principal.id, dup.id)], dry_run=False)

    db.refresh(principal)
    assert principal.radicado_23_digitos == "68001-2026-00060-00"
    assert principal.juzgado == "Juzgado Promiscuo Test"
    assert principal.ciudad == "Bucaramanga"


def test_idempotencia_already_merged(db, tmpdir_path):
    principal = _mk_case(db, tmpdir_path, name="P")
    dup = _mk_case(db, tmpdir_path, name="D", processing_status="DUPLICATE_MERGED")

    result = merge_duplicate_cases(db, [(principal.id, dup.id)], dry_run=False)
    assert result["skipped_already_merged"] == 1
    assert result["merged"] == 0


def test_audit_log_registrado(db, tmpdir_path):
    principal = _mk_case(db, tmpdir_path, name="P")
    dup = _mk_case(db, tmpdir_path, name="D")
    _mk_doc(db, dup, "x.pdf")

    merge_duplicate_cases(db, [(principal.id, dup.id)], dry_run=False)

    audits = db.query(AuditLog).filter(AuditLog.action == "MERGE_V6018").all()
    assert len(audits) >= 1
    assert audits[0].case_id == dup.id


def test_invalid_pair_returns_error(db, tmpdir_path):
    principal = _mk_case(db, tmpdir_path, name="P")
    result = merge_duplicate_cases(db, [(principal.id, 99999)], dry_run=True)
    assert result["errors"] == 1
    assert result["merged"] == 0
