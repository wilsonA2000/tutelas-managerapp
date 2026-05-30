"""Tests de extraccion global: run-all, stop, progress.

NOTA (fix flaky): el endpoint /api/extraction/run-all lanza la extraccion masiva
real en un hilo de fondo con un ProcessPoolExecutor. En produccion el server
sigue vivo y el `with ProcessPoolExecutor(...)` cierra los workers al terminar;
pero en pytest el proceso muere apenas pasa el assert, dejando los workers
forkeados HUERFANOS — y como un worker recien forkeado re-importa el backend y
se reconecta a la DB de produccion (no a la temporal de test), esos huerfanos
quedaban reteniendo data/tutelas.db y colgaban la siguiente corrida del gate.

El fixture autouse de abajo parchea el worker de fondo a un no-op: el contrato
del endpoint (setea el flag, arranca el hilo, responde "started"/"running") se
sigue probando, pero sin spawnear el pool real.
"""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _no_real_extraction_pool():
    """Evita que run-all spawnee el ProcessPool real (workers huerfanos)."""
    import backend.main

    backend.main.extraction_in_progress = False
    with patch.object(backend.main, "_run_extraction_background", lambda: None):
        yield
    backend.main.extraction_in_progress = False


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
