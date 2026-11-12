"""
tests/api/test_auth.py
Login, roles y gestión de usuarios de la web (interface/backend/auth.py y main.py).
"""
import pytest
from fastapi.testclient import TestClient

from interface.backend.auth import AuthError


@pytest.fixture
def client(monkeypatch, web_users):
    from interface.backend import main as main_module
    from interface.backend.api_handlers import ChatHandler

    monkeypatch.setattr(ChatHandler, "initialize_agent", lambda self, max_retries=3: (True, "ok"))
    monkeypatch.setattr("health.checker.get_health",
                        lambda requested_by="anonimo", force_refresh=False, store=None:
                        {"id": 1, "requested_by": requested_by, "forced": force_refresh})
    with TestClient(main_module.app) as c:
        yield c


def test_api_requires_login(client):
    assert client.post("/api/health-check").status_code == 401
    assert client.get("/api/health-history").status_code == 401


def test_wrong_password_is_rejected_and_locks_after_repeated_failures(client):
    for _ in range(5):
        r = client.post("/api/auth/login", json={"username": "user_consulta", "password": "mala-contrasena"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"username": "user_consulta", "password": "contrasena-de-prueba"})
    assert r.status_code == 429


def test_consulta_uses_cache_but_cannot_force_nor_see_detail_or_users(client, login_as):
    login_as(client, "consulta")
    r = client.post("/api/health-check")
    assert r.status_code == 200
    assert r.json() == {"id": 1, "requested_by": "user_consulta", "forced": False}
    assert client.post("/api/health-check?force=true").status_code == 403
    assert client.get("/api/health-check/1/detail").status_code == 403
    assert client.get("/api/users").status_code == 403


def test_dba_can_force_but_cannot_manage_users(client, login_as):
    login_as(client, "dba")
    assert client.post("/api/health-check?force=true").json()["forced"] is True
    assert client.get("/api/users").status_code == 403


def test_admin_manages_users_and_changes_apply_immediately(client, login_as):
    login_as(client, "administrador")
    r = client.post("/api/users", json={"username": "ana", "password": "Una-clave-2024", "role": "consulta"})
    assert r.status_code == 201
    assert "password_hash" not in r.json()

    other = TestClient(client.app)
    other.post("/api/auth/login", json={"username": "ana", "password": "Una-clave-2024"})
    assert other.get("/api/auth/me").json()["role"] == "consulta"

    client.patch("/api/users/ana", json={"role": "dba"})
    assert other.get("/api/auth/me").json()["role"] == "dba"

    client.patch("/api/users/ana", json={"active": False})
    assert other.get("/api/auth/me").status_code == 401


def test_logout_invalidates_session(client, login_as):
    login_as(client, "consulta")
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_last_active_admin_cannot_be_removed_or_demoted(web_users):
    with pytest.raises(AuthError):
        web_users.update("user_administrador", role="dba")
    with pytest.raises(AuthError):
        web_users.delete("user_administrador")


def test_short_password_is_rejected(web_users):
    with pytest.raises(AuthError):
        web_users.create("corta", "123", "consulta")


def test_unsafe_requests_need_the_session_csrf_token(client, login_as):
    login_as(client, "dba")
    token = client.headers.pop("X-CSRF-Token")
    assert client.post("/api/health-check").status_code == 403
    assert client.post("/api/health-check", headers={"X-CSRF-Token": "otro"}).status_code == 403
    assert client.post("/api/health-check", headers={"X-CSRF-Token": token}).status_code == 200
    assert client.get("/api/auth/me").json()["csrf"] == token


@pytest.mark.parametrize("password", [
    "solominusculas",          # una sola clase y corta
    "Clave-user_dba-2024",     # contiene el usuario
    "Password123",             # demasiado común
    "aaaaaaaaaaaaaaaaaaaa",    # predecible
])
def test_weak_passwords_are_rejected(web_users, password):
    with pytest.raises(AuthError):
        web_users.update("user_dba", password=password)


@pytest.mark.parametrize("password", ["Clave-2024x", "frase larga de varias palabras"])
def test_strong_passwords_and_passphrases_are_accepted(web_users, password):
    web_users.update("user_dba", password=password)
