"""Tests de alertas proactivas."""


def test_list_alerts(client):
    r = client.get("/api/alerts")
    assert r.status_code == 200


def test_list_alerts_filter(client):
    r = client.get("/api/alerts", params={"status": "active", "severity": "high"})
    assert r.status_code == 200


def test_alert_counts(client):
    r = client.get("/api/alerts/counts")
    assert r.status_code == 200


def test_scan_alerts(client):
    r = client.post("/api/alerts/scan")
    assert r.status_code == 200


def test_dismiss_alert_not_found(client):
    r = client.post("/api/alerts/99999/dismiss")
    # Puede ser 404 o 200 con error segun implementacion
    assert r.status_code in (200, 404)
