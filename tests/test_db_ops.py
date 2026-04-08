"""Tests de operaciones de DB: backup, restore, rebuild, sandbox compare."""

from unittest.mock import patch


def test_create_backup(client, auth_headers):
    mock_result = {"filename": "tutelas_backup_test.db", "size_mb": 1.5, "reason": "manual"}
    with patch("backend.routers.db.create_backup", return_value=mock_result):
        r = client.post("/api/db/backup", headers=auth_headers)
        assert r.status_code == 200
        assert "filename" in r.json()


def test_list_backups(client, auth_headers):
    mock_result = [{"filename": "test.db", "size_mb": 1, "created": "2026-04-08", "reason": "manual"}]
    with patch("backend.routers.db.list_backups", return_value=mock_result):
        r = client.get("/api/db/backups", headers=auth_headers)
        assert r.status_code == 200
        assert "backups" in r.json()


def test_restore_backup(client, auth_headers):
    mock_result = {"restored_from": "test.db", "size_mb": 1, "safety_backup": "safe.db"}
    with patch("backend.routers.db.restore_backup", return_value=mock_result):
        r = client.post("/api/db/restore", params={"filename": "test.db"}, headers=auth_headers)
        assert r.status_code == 200


def test_rebuild_start(client, auth_headers):
    r = client.post("/api/db/rebuild", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] in ("started", "running")


def test_rebuild_status(client, auth_headers):
    r = client.get("/api/db/rebuild/status", headers=auth_headers)
    assert r.status_code == 200
    assert "in_progress" in r.json()


def test_sandbox_compare(client, auth_headers):
    mock_result = {"main_cases": 3, "sandbox_cases": 0, "only_in_main": [], "only_in_sandbox": []}
    with patch("backend.services.rebuild_service.generate_comparison_report", return_value=mock_result):
        r = client.get("/api/db/sandbox/compare", headers=auth_headers)
        assert r.status_code == 200


def test_backup_no_auth_still_works(client):
    """Backup funciona sin auth (get_current_user retorna None)."""
    mock_result = {"filename": "test.db", "size_mb": 1}
    with patch("backend.routers.db.create_backup", return_value=mock_result):
        r = client.post("/api/db/backup")
        assert r.status_code == 200
