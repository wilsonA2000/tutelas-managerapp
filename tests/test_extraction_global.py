"""Tests de extraccion global: run-all, stop, progress."""


def test_extraction_progress(client):
    r = client.get("/api/extraction/progress")
    assert r.status_code == 200
    data = r.json()
    assert "in_progress" in data


def test_stop_extraction(client):
    r = client.post("/api/extraction/stop")
    assert r.status_code == 200


def test_run_all(client):
    r = client.post("/api/extraction/run-all")
    assert r.status_code == 200
    assert r.json()["status"] in ("started", "running", "empty")


def test_run_all_already_running(client):
    """Si ya esta corriendo, debe retornar status running."""
    import backend.main
    backend.main.extraction_in_progress = True
    r = client.post("/api/extraction/run-all")
    assert r.status_code == 200
    assert r.json()["status"] == "running"
    backend.main.extraction_in_progress = False
