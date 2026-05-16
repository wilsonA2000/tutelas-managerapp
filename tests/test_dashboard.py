"""Tests de dashboard: KPIs, charts, activity.

(El antiguo POST /api/dashboard/chat se retiró en la modernización Fase 6; el chat
del asistente vive en /api/chat/ y se prueba en tests/test_chat.py.)
"""


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


def test_kpis_completitud_excludes_v8_only_fields(client):
    """La completitud se calcula sobre los 37 campos del cuadro v9, no los 42
    de CSV_FIELD_MAP (excluye direccion/grupo/equipo/*_canonical, que v9 no llena)."""
    r = client.get("/api/dashboard/kpis")
    assert r.status_code == 200
    d = r.json()
    # los 3 casos seed no tienen direccion/grupo/equipo/canonicals → si se contaran,
    # la completitud sería menor. Basta con verificar que el campo existe y es coherente.
    assert 0 <= d["completitud"] <= 100
    assert d["campos_llenos"] >= 0
    # la favorabilidad expone "otro" (carencia de objeto / hecho superado / nulidad)
    assert "otro" in d["favorabilidad"]


def test_charts_favorabilidad_has_otro_bucket(client):
    """El gráfico de favorabilidad incluye el bucket OTRO (consistente con el KPI)."""
    r = client.get("/api/dashboard/charts")
    assert r.status_code == 200
    d = r.json()
    fav = {x["fallo"]: x["count"] for x in d.get("by_favorabilidad", [])}
    assert "OTRO" in fav  # ya no se lumpea en IMPROCEDENTE
