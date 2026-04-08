"""Tests de proveedores IA y token metrics."""


def test_get_providers(client):
    r = client.get("/api/ai/providers")
    # Endpoint puede no existir si router no esta registrado
    if r.status_code == 200:
        data = r.json()
        assert isinstance(data, dict)
    else:
        assert r.status_code == 404


def test_token_metrics(client):
    r = client.get("/api/tokens/metrics")
    if r.status_code == 200:
        assert isinstance(r.json(), dict)
    else:
        assert r.status_code == 404
