"""Tests de integridad de datos: cascade, FK, unique constraints."""

from sqlalchemy.exc import IntegrityError
import pytest


def test_case_has_documents(client, case_ids):
    """Caso 1 debe tener documentos asociados."""
    r = client.get(f"/api/cases/{case_ids[0]}")
    docs = r.json()["documents"]
    assert len(docs) >= 1


def test_audit_log_on_update(client, case_ids):
    """Actualizar un campo debe generar un audit log."""
    # Actualizar campo
    client.put(f"/api/cases/{case_ids[1]}", json={"DERECHO_VULNERADO": "EDUCACION"})

    # Verificar audit log
    r = client.get(f"/api/cases/{case_ids[1]}")
    audit = r.json().get("audit_log", [])
    found = any(
        a["field_name"] == "DERECHO_VULNERADO" and a["new_value"] == "EDUCACION"
        for a in audit
    )
    assert found, "Audit log no registrado para actualizacion"


def test_duplicate_folder_name_rejected(TestSessionFactory):
    """No debe permitir dos casos con el mismo folder_name."""
    from backend.database.models import Case

    db = TestSessionFactory()
    try:
        c = Case(folder_name="2026-00001 JUAN PEREZ GOMEZ", processing_status="PENDIENTE")
        db.add(c)
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_foreign_key_document(TestSessionFactory):
    """Documento con case_id inexistente debe fallar por FK."""
    from backend.database.models import Document

    db = TestSessionFactory()
    try:
        d = Document(case_id=99999, filename="test.pdf", file_path="/tmp/test.pdf")
        db.add(d)
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_email_fields_complete(client, email_ids):
    """Emails deben tener campos obligatorios."""
    r = client.get(f"/api/emails/detail/{email_ids[0]}")
    assert r.status_code == 200
    data = r.json()
    assert data.get("subject")
    assert data.get("sender")


def test_case_fields_types(client, case_ids):
    """Campos del caso deben ser del tipo correcto."""
    r = client.get(f"/api/cases/{case_ids[0]}")
    data = r.json()
    assert isinstance(data["id"], int)
    assert isinstance(data.get("ACCIONANTE", ""), str)
    assert isinstance(data.get("documents", []), list)
