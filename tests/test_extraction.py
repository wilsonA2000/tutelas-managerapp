"""Tests de extraccion: review, suspicious, verify, mark-ok, move, suggest-target."""

from unittest.mock import patch


def test_review_queue(client):
    r = client.get("/api/extraction/review")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    # Debe haber casos en PENDIENTE o REVISION
    assert len(data) >= 2


def test_review_queue_has_alert_counts(client):
    """Review queue debe incluir docs_no_pertenece y docs_sospechosos."""
    r = client.get("/api/extraction/review")
    data = r.json()
    if data:
        assert "docs_no_pertenece" in data[0]
        assert "docs_sospechosos" in data[0]


def test_suspicious_docs(client):
    r = client.get("/api/extraction/suspicious-docs")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    # Debe haber al menos 1 (NO_PERTENECE) + 1 (SOSPECHOSO)
    assert len(data) >= 2


def test_duplicate_docs(client):
    r = client.get("/api/extraction/duplicate-docs")
    assert r.status_code == 200


def test_mismatched_docs(client):
    r = client.get("/api/extraction/mismatched-docs")
    assert r.status_code == 200


def test_mark_doc_ok(client, doc_ids):
    """Marcar doc SOSPECHOSO como OK."""
    r = client.post(f"/api/extraction/docs/{doc_ids[2]}/mark-ok")
    assert r.status_code == 200
    assert "OK" in r.json().get("message", "")


def test_mark_doc_ok_not_found(client):
    r = client.post("/api/extraction/docs/99999/mark-ok")
    assert r.status_code == 404


def test_suggest_target(client, doc_ids):
    """Sugerir caso destino para doc NO_PERTENECE."""
    r = client.get(f"/api/extraction/docs/{doc_ids[3]}/suggest-target")
    assert r.status_code == 200
    data = r.json()
    assert "suggestions" in data
    assert "filename" in data


def test_suggest_target_not_found(client):
    r = client.get("/api/extraction/docs/99999/suggest-target")
    assert r.status_code == 404


def test_move_doc(client, doc_ids, case_ids):
    """Mover documento a otro caso."""
    r = client.post(f"/api/extraction/docs/{doc_ids[4]}/move/{case_ids[1]}")
    assert r.status_code == 200


def test_move_doc_not_found(client, case_ids):
    r = client.post(f"/api/extraction/docs/99999/move/{case_ids[0]}")
    assert r.status_code == 404


def test_single_extraction_not_found(client):
    r = client.post("/api/extraction/single/99999", timeout=10)
    assert r.status_code == 404


def test_single_extraction_mock(client, case_ids):
    mock_stats = {
        "ai_fields_extracted": 5,
        "documents_extracted": 2,
        "documents_failed": 0,
    }
    with patch("backend.routers.extraction.process_folder", return_value=mock_stats):
        r = client.post(f"/api/extraction/single/{case_ids[0]}", timeout=10)
        assert r.status_code == 200


def test_batch_extraction(client, case_ids):
    """Batch extraction inicia en background."""
    r = client.post("/api/extraction/batch", json={"case_ids": case_ids[:1]})
    assert r.status_code == 200
    assert r.json()["status"] in ("started", "running", "empty")


def test_verify_all_mock(client):
    mock_result = {"total": 5, "ok": 3, "sospechoso": 1, "no_pertenece": 1}
    with patch("backend.extraction.pipeline.verify_all_documents", return_value=mock_result):
        r = client.post("/api/extraction/verify-all", timeout=30)
        assert r.status_code == 200


def test_dismiss_all_mismatched(client):
    r = client.delete("/api/extraction/mismatched-docs")
    assert r.status_code == 200
