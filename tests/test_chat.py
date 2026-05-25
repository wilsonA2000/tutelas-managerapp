"""Tests para chat NL→DB (Tier 1: regex deterministas)."""
import pytest

# Usa el fixture `client` del conftest (TestClient autenticado + DB de test). Antes
# este módulo creaba su propio `TestClient(app)` a nivel de módulo, que (a) no pasaba
# por el AuthMiddleware con token → 401, y (b) no usaba la DB de test. Por eso fallaba
# toda la suite de chat con 401.


@pytest.mark.parametrize("question,expected_intent,min_conf", [
    # Overview
    ("Dame el resumen general", "overview", 0.9),
    ("¿Cuántos casos tenemos?", "overview", 0.9),
    ("estadísticas", "overview", 0.9),
    # Estado_incidente
    ("¿Cuántos casos hay en sanción?", "count_by_estado_incidente", 0.8),
    ("casos cumplidos", "count_by_estado_incidente", 0.8),
    ("Casos activos de incidente", "count_by_estado_incidente", 0.8),
    # Municipio
    ("¿Tutelas en Bucaramanga?", "cases_by_municipio", 0.8),
    ("Casos en Floridablanca", "cases_by_municipio", 0.8),
    ("tutelas en Piedecuesta", "cases_by_municipio", 0.8),
    # Detalle
    ("Detalle del caso 119", "case_detail", 0.9),
    ("Información caso 295", "case_detail", 0.9),
    ("caso #200", "case_detail", 0.9),
    # Accionante
    ("Casos de Wilson Arguello", "search_accionante", 0.8),
    # Pendientes
    ("Impugnaciones pendientes", "pending_impugnacion", 0.8),
    ("Casos sin segunda instancia", "pending_impugnacion", 0.8),
    # Top accionados
    ("¿Qué entidades son más demandadas?", "top_accionados", 0.8),
    ("top demandados", "top_accionados", 0.8),
    # Monthly
    ("tutelas por mes", "monthly_trends", 0.8),
    ("tendencia mensual", "monthly_trends", 0.8),
    # Unknown
    ("Cuéntame un chiste", "unknown", 0.0),
    ("qué hora es", "unknown", 0.0),
])
def test_intent_routing(client, question, expected_intent, min_conf):
    r = client.post("/api/chat/", json={"message": question})
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
    d = r.json()
    assert d["intent"] == expected_intent, f"got {d['intent']!r} for {question!r}"
    assert d["confidence"] >= min_conf, f"conf {d['confidence']} < {min_conf} for {question!r}"
    assert "answer" in d


def test_health(client):
    r = client.get("/api/chat/health")
    assert r.status_code == 200
    d = r.json()
    assert d["tier1_intents"] >= 7
    assert "tier2_llm" in d


def test_intents_list(client):
    r = client.get("/api/chat/intents")
    assert r.status_code == 200
    intents = r.json()
    assert len(intents) >= 7
    for it in intents:
        assert "name" in it
        assert "description" in it


def test_overview_data_structure(client):
    r = client.post("/api/chat/", json={"message": "resumen"})
    assert r.status_code == 200
    d = r.json()
    assert d["intent"] == "overview"
    assert "data" in d
    assert d["data"]["total"] > 0
    assert "by_status" in d["data"]


def test_case_detail_invalid_id(client):
    r = client.post("/api/chat/", json={"message": "caso 99999"})
    assert r.status_code == 200
    d = r.json()
    assert d["intent"] == "case_detail"
    assert "no encontré" in d["answer"].lower() or "no encontre" in d["answer"].lower()


def test_municipio_unknown_falls_through(client):
    """Si no se identifica municipio, debe hacer fallthrough a otros intents."""
    r = client.post("/api/chat/", json={"message": "Casos de Wilson Arguello"})
    assert r.status_code == 200
    d = r.json()
    # Debe ser search_accionante, no cases_by_municipio
    assert d["intent"] == "search_accionante"


def test_empty_message(client):
    r = client.post("/api/chat/", json={"message": ""})
    assert r.status_code == 200
    assert r.json()["intent"] == "empty"
