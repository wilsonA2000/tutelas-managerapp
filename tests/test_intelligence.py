"""Tests de inteligencia legal: favorability, appeals, lawyers, trends, rights, predict, calendar, deadlines."""


def test_favorability(client):
    r = client.get("/api/intelligence/favorability")
    assert r.status_code == 200


def test_appeals(client):
    r = client.get("/api/intelligence/appeals")
    assert r.status_code == 200


def test_lawyers(client):
    r = client.get("/api/intelligence/lawyers")
    assert r.status_code == 200


def test_trends(client):
    r = client.get("/api/intelligence/trends")
    assert r.status_code == 200


def test_rights(client):
    r = client.get("/api/intelligence/rights")
    assert r.status_code == 200


def test_predict(client):
    r = client.get("/api/intelligence/predict", params={"juzgado": "PRIMERO", "derecho": "SALUD", "ciudad": "BUCARAMANGA"})
    assert r.status_code == 200


def test_calendar(client):
    r = client.get("/api/intelligence/calendar")
    assert r.status_code == 200


def test_deadlines(client):
    r = client.get("/api/intelligence/deadlines")
    assert r.status_code == 200
