"""Tests de emails: list, detail, assign, ignore, gmail-stats, check."""

from unittest.mock import patch


def test_list_emails(client):
    r = client.get("/api/emails")
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert data["total"] >= 2


def test_list_emails_filter_status(client):
    r = client.get("/api/emails", params={"status": "PENDIENTE"})
    assert r.status_code == 200


def test_get_email_detail(client, email_ids):
    r = client.get(f"/api/emails/detail/{email_ids[0]}")
    assert r.status_code == 200
    data = r.json()
    assert "subject" in data


def test_get_email_not_found(client):
    r = client.get("/api/emails/detail/99999")
    assert r.status_code == 404


def test_assign_email(client, email_ids, case_ids):
    r = client.put(f"/api/emails/{email_ids[1]}/assign/{case_ids[1]}")
    assert r.status_code == 200


def test_assign_email_not_found(client, case_ids):
    r = client.put(f"/api/emails/99999/assign/{case_ids[0]}")
    assert r.status_code == 404


def test_ignore_email(client, email_ids):
    r = client.put(f"/api/emails/{email_ids[1]}/ignore")
    assert r.status_code == 200


def test_ignore_email_not_found(client):
    r = client.put("/api/emails/99999/ignore")
    assert r.status_code == 404


def test_gmail_stats(client):
    with patch("backend.main.get_gmail_total", return_value={"total": 100, "unread": 5}):
        r = client.get("/api/emails/gmail-stats")
        assert r.status_code == 200
        data = r.json()
        assert "db_total" in data


def test_check_status(client):
    r = client.get("/api/emails/check-status")
    assert r.status_code == 200
    assert "in_progress" in r.json()


def test_check_cancel(client):
    r = client.post("/api/emails/check-cancel")
    assert r.status_code == 200
