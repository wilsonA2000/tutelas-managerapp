"""Tests de health check, normalizer, settings y monitor."""


def test_health_check(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "Tutelas Manager" in data["app"]


def test_health_normalizer(client):
    r = client.get("/api/health/normalizer")
    assert r.status_code == 200
    data = r.json()
    assert "normalizer_enabled" in data or "error" in data


def test_settings_status(client):
    r = client.get("/api/settings/status")
    assert r.status_code == 200
    data = r.json()
    for key in ("gmail", "groq", "database", "folders"):
        assert key in data


def test_monitor_status(client):
    r = client.get("/api/monitor/status")
    assert r.status_code == 200
    data = r.json()
    assert "enabled" in data
    assert "interval_minutes" in data
    assert "log" in data


def test_monitor_toggle(client):
    r = client.post("/api/monitor/toggle")
    assert r.status_code == 200
    data = r.json()
    assert "enabled" in data
    first_state = data["enabled"]

    # Toggle back
    r2 = client.post("/api/monitor/toggle")
    assert r2.json()["enabled"] != first_state
