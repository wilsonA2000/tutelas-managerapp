"""Tests de seguimiento de cumplimiento."""

from unittest.mock import patch


def test_list_seguimiento(client):
    r = client.get("/api/seguimiento")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data or isinstance(data, list)


def test_list_seguimiento_filter(client):
    r = client.get("/api/seguimiento", params={"estado": "PENDIENTE"})
    assert r.status_code == 200


def test_resumen(client):
    r = client.get("/api/seguimiento/resumen")
    assert r.status_code == 200


def test_scan_fallos(client):
    r = client.post("/api/seguimiento/scan")
    assert r.status_code == 200
    data = r.json()
    assert "created" in data or "scanned" in data or isinstance(data, dict)


def test_get_seguimiento_not_found(client):
    r = client.get("/api/seguimiento/99999")
    assert r.status_code == 404


def test_update_seguimiento_not_found(client):
    r = client.put("/api/seguimiento/99999", json={"estado": "CUMPLIDO"})
    assert r.status_code == 404
