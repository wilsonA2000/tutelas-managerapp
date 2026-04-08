"""Tests de autenticacion: login, refresh, me, change-password."""


def test_login_success(client):
    r = client.post("/api/auth/login", json={"username": "testadmin", "password": "test123"})
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["username"] == "testadmin"


def test_login_wrong_password(client):
    r = client.post("/api/auth/login", json={"username": "testadmin", "password": "wrong"})
    assert r.status_code == 401


def test_login_nonexistent_user(client):
    r = client.post("/api/auth/login", json={"username": "noexiste", "password": "test123"})
    assert r.status_code == 401


def test_login_missing_fields(client):
    r = client.post("/api/auth/login", json={})
    assert r.status_code == 422


def test_refresh_valid(client):
    login = client.post("/api/auth/login", json={"username": "testadmin", "password": "test123"})
    refresh_token = login.json()["refresh_token"]

    r = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_refresh_invalid_token(client):
    r = client.post("/api/auth/refresh", json={"refresh_token": "invalid.token.here"})
    assert r.status_code == 401


def test_me_authenticated(client, auth_headers):
    r = client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["username"] == "testadmin"
    assert "role" in data


def test_me_no_token(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_me_invalid_token(client):
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid.token"})
    assert r.status_code == 401


def test_change_password_wrong_current(client, auth_headers):
    r = client.post("/api/auth/change-password", json={
        "current_password": "wrongpassword",
        "new_password": "newpass123",
    }, headers=auth_headers)
    assert r.status_code == 400
