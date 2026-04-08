"""Tests de dashboard: KPIs, charts, activity, chat."""

from unittest.mock import patch


def test_kpis(client):
    r = client.get("/api/dashboard/kpis")
    assert r.status_code == 200
    data = r.json()
    assert "total_casos" in data
    assert data["total_casos"] >= 3


def test_charts(client):
    r = client.get("/api/dashboard/charts")
    assert r.status_code == 200
    data = r.json()
    assert "by_city" in data or "by_fallo" in data


def test_activity(client):
    r = client.get("/api/dashboard/activity")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


def test_chat_mock(client):
    mock_result = {"answer": "Test response", "steps": [], "tools_used": []}
    with patch("backend.agent.runner.run_agent", return_value=mock_result):
        r = client.post("/api/dashboard/chat", json={"question": "cuantos casos hay?"})
        assert r.status_code == 200
