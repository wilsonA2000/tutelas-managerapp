"""Tests de regresion: bugs conocidos y edge cases."""


def test_forest_blacklist_3634740():
    """FOREST alucinado '3634740' NUNCA debe ser valido."""
    from backend.agent.forest_extractor import is_valid_forest
    assert is_valid_forest("3634740") is False


def test_forest_judicial_radicado_not_forest():
    """Numeros 68xxx (radicado judicial) no son FOREST."""
    from backend.agent.forest_extractor import is_valid_forest
    assert is_valid_forest("68001400900") is False


def test_forest_valid_number():
    """FOREST valido debe tener 10-11 digitos."""
    from backend.agent.forest_extractor import is_valid_forest
    assert is_valid_forest("20260123456") is True


def test_is_case_folder_valid():
    """Carpetas que empiezan con 202X son validas."""
    from backend.database.seed import is_case_folder
    assert is_case_folder("2026-00001 JUAN PEREZ")
    assert is_case_folder("2025-0014 MARIA")
    assert not is_case_folder("COMUNICACIONES")
    assert not is_case_folder("tutelas-app")
    assert not is_case_folder(".git")


def test_classify_doc_type():
    """Clasificacion de documentos por nombre."""
    from backend.extraction.pipeline import classify_doc_type
    assert "GMAIL" in classify_doc_type("Gmail - RV_ Tutela.pdf")


def test_update_case_null_value(client, case_ids):
    """PUT con valor vacio no debe corromper DB."""
    r = client.put(f"/api/cases/{case_ids[0]}", json={"OBSERVACIONES": ""})
    assert r.status_code == 200


def test_sync_status_initial(client):
    """Sync status debe retornar in_progress=False cuando no hay sync."""
    r = client.get("/api/sync/status")
    assert r.status_code == 200
    assert r.json()["in_progress"] is False
