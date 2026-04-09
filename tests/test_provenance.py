"""Tests v4.8 Provenance: paquetes email inmutables + hermanos viajan juntos.

Valida que:
1. La migración de schema agrega las columnas correctamente
2. `get_siblings()` devuelve hermanos del mismo email_id
3. Docs legacy (sin email_id) devuelven lista vacía de siblings
4. `get_package_by_email()` construye el paquete completo
5. `preview_package_move()` indica el número correcto de hermanos
6. `move_document_or_package()` mueve TODOS los hermanos cuando hay email_id
7. `move_document_or_package()` mueve SOLO el doc cuando email_id es NULL
8. Idempotencia: el backfill no duplica vínculos al re-correrse
"""

import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database.models import Base, Case, Document, Email


@pytest.fixture
def provenance_db(tmp_path):
    """DB temporal con schema v4.8 y datos de prueba."""
    db_path = tmp_path / "test_provenance.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    db = SessionLocal()
    # 2 casos
    case_a = Case(folder_name="2026-00001 JUAN PEREZ", folder_path=str(tmp_path / "case_a"), processing_status="COMPLETO")
    case_b = Case(folder_name="2026-00002 MARIA LOPEZ", folder_path=str(tmp_path / "case_b"), processing_status="COMPLETO")
    db.add_all([case_a, case_b])
    db.flush()

    # Crear carpetas reales para test de move
    (tmp_path / "case_a").mkdir()
    (tmp_path / "case_b").mkdir()

    # 1 Email con 3 adjuntos + 1 .md (paquete de 4 docs)
    email_pkg = Email(
        message_id="msg_001",
        subject="RV: NOTIFICACIÓN AUTO ADMISORIO",
        sender="juzgado@example.com",
        date_received=datetime(2026, 4, 1),
        body_preview="Contenido del email",
        case_id=case_a.id,
        attachments=[],
        status="ASIGNADO",
    )
    db.add(email_pkg)
    db.flush()

    # Crear archivos reales en disco
    (tmp_path / "case_a" / "auto.pdf").write_text("pdf content")
    (tmp_path / "case_a" / "escrito.pdf").write_text("pdf content")
    (tmp_path / "case_a" / "anexo.pdf").write_text("pdf content")
    (tmp_path / "case_a" / "Email_20260401_NOTIFICACION.md").write_text("md content")

    # 4 Documents hijos del mismo email_id
    docs_pkg = [
        Document(case_id=case_a.id, filename="auto.pdf", file_path=str(tmp_path / "case_a" / "auto.pdf"),
                 doc_type="AUTO_ADMISORIO", email_id=email_pkg.id, email_message_id="msg_001"),
        Document(case_id=case_a.id, filename="escrito.pdf", file_path=str(tmp_path / "case_a" / "escrito.pdf"),
                 doc_type="OTRO", email_id=email_pkg.id, email_message_id="msg_001"),
        Document(case_id=case_a.id, filename="anexo.pdf", file_path=str(tmp_path / "case_a" / "anexo.pdf"),
                 doc_type="OTRO", email_id=email_pkg.id, email_message_id="msg_001"),
        Document(case_id=case_a.id, filename="Email_20260401_NOTIFICACION.md", file_path=str(tmp_path / "case_a" / "Email_20260401_NOTIFICACION.md"),
                 doc_type="EMAIL_MD", email_id=email_pkg.id, email_message_id="msg_001"),
    ]
    db.add_all(docs_pkg)

    # 1 Document legacy sin email_id
    (tmp_path / "case_a" / "legacy.pdf").write_text("legacy")
    legacy_doc = Document(
        case_id=case_a.id, filename="legacy.pdf",
        file_path=str(tmp_path / "case_a" / "legacy.pdf"),
        doc_type="OTRO", email_id=None, email_message_id=None,
    )
    db.add(legacy_doc)

    db.commit()

    yield db, case_a, case_b, email_pkg, docs_pkg, legacy_doc

    db.close()


# ============================================================
# Test 1: Schema — las columnas existen
# ============================================================

def test_schema_has_email_provenance_columns(provenance_db):
    db, *_ = provenance_db
    from sqlalchemy import inspect
    inspector = inspect(db.bind)
    cols = {c["name"] for c in inspector.get_columns("documents")}
    assert "email_id" in cols
    assert "email_message_id" in cols


# ============================================================
# Test 2: get_siblings devuelve paquete completo
# ============================================================

def test_get_siblings_returns_all_package_members(provenance_db):
    from backend.services.provenance_service import get_siblings

    db, case_a, case_b, email_pkg, docs_pkg, legacy = provenance_db
    # Doc 0 (auto.pdf) es parte del paquete de 4 docs
    siblings = get_siblings(db, docs_pkg[0].id)
    assert len(siblings) == 4
    ids_returned = {s.id for s in siblings}
    ids_expected = {d.id for d in docs_pkg}
    assert ids_returned == ids_expected


# ============================================================
# Test 3: Legacy doc devuelve lista vacía
# ============================================================

def test_legacy_doc_has_no_siblings(provenance_db):
    from backend.services.provenance_service import get_siblings, has_siblings

    db, _, _, _, _, legacy = provenance_db
    siblings = get_siblings(db, legacy.id)
    assert siblings == []
    assert has_siblings(db, legacy.id) is False


# ============================================================
# Test 4: get_package_by_email construye el paquete
# ============================================================

def test_get_package_by_email(provenance_db):
    from backend.services.provenance_service import get_package_by_email

    db, case_a, _, email_pkg, docs_pkg, _ = provenance_db
    pkg = get_package_by_email(db, email_pkg.id)
    assert pkg is not None
    assert pkg["count"] == 4
    assert pkg["case_id"] == case_a.id
    assert pkg["email"].message_id == "msg_001"
    assert len(pkg["documents"]) == 4


# ============================================================
# Test 5: preview_package_move indica el número correcto
# ============================================================

def test_preview_package_move_reports_correct_count(provenance_db):
    from backend.services.sibling_mover import preview_package_move

    db, _, _, _, docs_pkg, legacy = provenance_db

    # Doc del paquete → debe reportar 4 hermanos
    preview = preview_package_move(db, docs_pkg[0].id)
    assert preview["package_mode"] is True
    assert preview["siblings_count"] == 4
    assert "3 hermanos" in preview["message"]  # 4 - 1 = 3 otros

    # Doc legacy → debe reportar modo individual
    preview_legacy = preview_package_move(db, legacy.id)
    assert preview_legacy["package_mode"] is False
    assert preview_legacy["siblings_count"] == 1


# ============================================================
# Test 6: move_document_or_package mueve TODO el paquete
# ============================================================

def test_move_package_moves_all_siblings(provenance_db, tmp_path):
    from backend.services.sibling_mover import move_document_or_package

    db, case_a, case_b, email_pkg, docs_pkg, _ = provenance_db

    # Mover el primer doc del paquete a case_b
    result = move_document_or_package(db, docs_pkg[0].id, case_b.id)
    db.commit()

    assert result["package_mode"] is True
    assert len(result["moved_ids"]) == 4  # todos los hermanos movidos
    assert not result["errors"]

    # Todos los docs del paquete ahora apuntan a case_b
    db.expire_all()
    for d_original in docs_pkg:
        fresh = db.query(Document).filter(Document.id == d_original.id).first()
        assert fresh.case_id == case_b.id
        # Archivo movido en disco
        assert "case_b" in fresh.file_path
        assert Path(fresh.file_path).exists()


# ============================================================
# Test 7: move de legacy doc solo mueve ese doc
# ============================================================

def test_move_legacy_doc_does_not_affect_other_docs(provenance_db):
    from backend.services.sibling_mover import move_document_or_package

    db, case_a, case_b, _, docs_pkg, legacy = provenance_db

    result = move_document_or_package(db, legacy.id, case_b.id)
    db.commit()

    assert result["package_mode"] is False
    assert len(result["moved_ids"]) == 1
    assert result["moved_ids"][0] == legacy.id

    # El legacy fue movido
    db.refresh(legacy)
    assert legacy.case_id == case_b.id

    # Los docs del paquete NO fueron movidos
    for d in docs_pkg:
        db.refresh(d)
        assert d.case_id == case_a.id  # intactos


# ============================================================
# Test 8: Idempotencia de la migración de schema
# ============================================================

def test_migration_schema_is_idempotent(tmp_path):
    from backend.database.migrations.v48_add_email_provenance import run

    # Crear DB con schema base
    db_path = tmp_path / "test_migration.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # Correr migración 2 veces — segunda corrida debe skip todo
    r1 = run(db_path=str(db_path))
    # Primera corrida: como Base.metadata.create_all ya creó las columnas
    # (porque están en el modelo), la migración debe saltarlas
    assert r1["status"] == "ok"

    r2 = run(db_path=str(db_path))
    assert r2["status"] == "ok"
    # Segunda corrida no debe hacer nada nuevo
    assert len(r2["actions"]) == 0
    assert len(r2["skipped"]) >= 2  # columnas ya existen


# ============================================================
# Test 9: Relationship Email.documents funciona
# ============================================================

def test_email_relationship_to_documents(provenance_db):
    db, _, _, email_pkg, docs_pkg, _ = provenance_db
    # SQLAlchemy relationship debe devolver los 4 hijos
    db.refresh(email_pkg)
    assert len(email_pkg.documents) == 4
    doc_ids = {d.id for d in email_pkg.documents}
    expected = {d.id for d in docs_pkg}
    assert doc_ids == expected


# ============================================================
# Test 10: list_packages_in_case orden por fecha
# ============================================================

def test_list_packages_in_case(provenance_db):
    from backend.services.provenance_service import list_packages_in_case

    db, case_a, _, email_pkg, _, _ = provenance_db
    packages = list_packages_in_case(db, case_a.id)
    assert len(packages) == 1
    assert packages[0]["email_id"] == email_pkg.id
    assert packages[0]["document_count"] == 4
    assert packages[0]["subject"] == "RV: NOTIFICACIÓN AUTO ADMISORIO"
