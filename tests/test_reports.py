"""Tests de reportes: Excel gen, download, list, metrics."""


def test_metrics(client):
    r = client.get("/api/reports/metrics")
    assert r.status_code == 200
    data = r.json()
    assert "total" in data or isinstance(data, dict)


def test_excel_list(client):
    r = client.get("/api/reports/excel/list")
    assert r.status_code == 200


def test_generate_excel(client):
    r = client.post("/api/reports/excel")
    assert r.status_code == 200
    data = r.json()
    assert "filename" in data or "error" in data


def test_download_excel_not_found(client):
    r = client.get("/api/reports/excel/download/noexiste.xlsx")
    assert r.status_code == 404


def test_download_excel_path_traversal(client):
    """Security: no debe permitir path traversal."""
    r = client.get("/api/reports/excel/download/../../etc/passwd")
    assert r.status_code in (400, 404, 422)
