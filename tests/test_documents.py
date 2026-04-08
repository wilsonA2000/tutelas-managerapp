"""Tests de documentos: get, preview, not found."""


def test_get_document(client, doc_ids):
    r = client.get(f"/api/documents/{doc_ids[0]}")
    assert r.status_code == 200
    data = r.json()
    assert "filename" in data
    assert "doc_type" in data


def test_get_document_not_found(client):
    r = client.get("/api/documents/99999")
    assert r.status_code == 404


def test_preview_document_pdf(client, doc_ids):
    """Preview de PDF dummy — archivo existe pero no es PDF valido."""
    r = client.get(f"/api/documents/{doc_ids[0]}/preview")
    # El archivo dummy existe, debe retornar 200 con el contenido
    assert r.status_code == 200


def test_preview_document_not_found(client):
    r = client.get("/api/documents/99999/preview")
    assert r.status_code == 404


def test_document_has_verificacion(client, case_ids):
    """Verificar que los documentos incluyen campo verificacion."""
    r = client.get(f"/api/cases/{case_ids[0]}")
    assert r.status_code == 200
    docs = r.json().get("documents", [])
    assert len(docs) > 0
    assert "verificacion" in docs[0]


def test_document_no_pertenece_exists(client, case_ids):
    """Verificar que hay al menos un documento NO_PERTENECE en los datos de test."""
    r = client.get(f"/api/cases/{case_ids[2]}")
    assert r.status_code == 200
    docs = r.json().get("documents", [])
    no_pert = [d for d in docs if d.get("verificacion") == "NO_PERTENECE"]
    assert len(no_pert) >= 1


def test_document_sospechoso_exists(client, case_ids):
    """Verificar que hay al menos un documento SOSPECHOSO."""
    r = client.get(f"/api/cases/{case_ids[1]}")
    assert r.status_code == 200
    docs = r.json().get("documents", [])
    sosp = [d for d in docs if d.get("verificacion") == "SOSPECHOSO"]
    assert len(sosp) >= 1
