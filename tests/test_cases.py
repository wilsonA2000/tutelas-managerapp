"""Tests de CRUD de casos: list, get, update, delete, merge, sync, table, filters."""


def test_list_cases(client):
    r = client.get("/api/cases")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 3


def test_list_cases_pagination(client):
    r = client.get("/api/cases", params={"page": 1, "per_page": 2})
    assert r.status_code == 200
    assert len(r.json()["items"]) <= 2


def test_list_cases_search(client):
    r = client.get("/api/cases", params={"search": "JUAN"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert any("JUAN" in (i.get("ACCIONANTE") or "").upper() for i in items)


def test_list_cases_filter_estado(client):
    r = client.get("/api/cases", params={"estado": "ACTIVO"})
    assert r.status_code == 200


def test_list_cases_filter_status(client):
    r = client.get("/api/cases", params={"status": "COMPLETO"})
    assert r.status_code == 200


def test_get_filters(client):
    r = client.get("/api/cases/filters")
    assert r.status_code == 200
    data = r.json()
    assert "ciudades" in data or "estados" in data


def test_get_case_table(client):
    r = client.get("/api/cases/table")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    if data:
        assert "folder_name" in data[0]
        assert "completitud" in data[0]


def test_get_case_by_id(client, case_ids):
    r = client.get(f"/api/cases/{case_ids[0]}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == case_ids[0]
    assert "documents" in data
    assert "audit_log" in data


def test_get_case_not_found(client):
    r = client.get("/api/cases/99999")
    assert r.status_code == 404


def test_update_case(client, case_ids):
    r = client.put(f"/api/cases/{case_ids[0]}", json={"OBSERVACIONES": "Test observation E2E"})
    assert r.status_code == 200

    # Verificar que se actualizo
    r2 = client.get(f"/api/cases/{case_ids[0]}")
    assert "Test observation E2E" in r2.json().get("OBSERVACIONES", "")


def test_update_case_not_found(client):
    r = client.put("/api/cases/99999", json={"OBSERVACIONES": "test"})
    assert r.status_code == 404


def test_update_case_generates_audit(client, case_ids):
    r = client.put(f"/api/cases/{case_ids[0]}", json={"ASUNTO": "Tutela test audit"})
    assert r.status_code == 200

    case = client.get(f"/api/cases/{case_ids[0]}").json()
    audit = case.get("audit_log", [])
    assert any(a["field_name"] == "ASUNTO" and a["action"] == "EDICION_MANUAL" for a in audit)


def test_sync_single_case(client, case_ids):
    r = client.post(f"/api/cases/{case_ids[0]}/sync")
    assert r.status_code == 200


def test_delete_document_not_found(client, case_ids):
    r = client.delete(f"/api/cases/{case_ids[0]}/docs/99999")
    assert r.status_code == 404


def test_merge_case_not_found(client, case_ids):
    r = client.post(f"/api/cases/99999/merge/{case_ids[0]}")
    assert r.status_code == 404


def test_merge_case_target_not_found(client, case_ids):
    r = client.post(f"/api/cases/{case_ids[0]}/merge/99999")
    assert r.status_code == 404
