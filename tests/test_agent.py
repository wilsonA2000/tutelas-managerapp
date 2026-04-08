"""Tests del agente IA: run, tools, routes, tokens, budget."""

from unittest.mock import patch


def test_agent_tools(client):
    r = client.get("/api/agent/tools")
    assert r.status_code == 200
    data = r.json()
    assert "tools" in data or "count" in data


def test_agent_routes(client):
    r = client.get("/api/agent/routes")
    assert r.status_code == 200


def test_agent_run_mock(client):
    mock_result = {
        "answer": "Hay 3 casos de prueba.",
        "steps": [{"tool": "search_cases", "result": "3 found"}],
        "tools_used": ["search_cases"],
    }
    with patch("backend.agent.runner.run_agent", return_value=mock_result):
        r = client.post("/api/agent/run", json={"instruction": "cuantos casos hay?"}, timeout=10)
        assert r.status_code == 200


def test_agent_tokens(client):
    r = client.get("/api/agent/tokens")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)


def test_agent_budget(client):
    r = client.post("/api/agent/tokens/budget", json={"daily_limit_usd": 5.0, "monthly_limit_usd": 50.0})
    assert r.status_code == 200
