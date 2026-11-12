"""
tests/conftest.py
Fixtures compartidas: cursor/conexion Oracle simulados y cliente de la API.
"""
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage


@pytest.fixture
def fake_cursor():
    """Cursor simulado utilizable como context manager (with conn.cursor() as cur)."""
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    return cursor


@pytest.fixture
def fake_connection(fake_cursor):
    conn = MagicMock()
    conn.cursor.return_value = fake_cursor
    return conn


@pytest.fixture
def mock_db_connection(monkeypatch, fake_connection):
    """Parchea db.queries.get_connection (nombre importado, no el módulo origen)."""
    monkeypatch.setattr("db.queries.get_connection", lambda: fake_connection)
    return fake_connection


def set_query_result(fake_cursor, columns: list[str], rows: list[tuple]) -> None:
    """Configura fake_cursor para que _fetchall_as_dicts devuelva las filas dadas."""
    fake_cursor.description = [(col,) for col in columns]
    fake_cursor.fetchall.return_value = rows


TEST_PASSWORD = "contrasena-de-prueba"


@pytest.fixture
def web_users(monkeypatch, tmp_path_factory):
    """Usuarios de la web aislados por test (uno por rol) con hash rápido."""
    from interface.backend import auth
    from interface.backend import main as main_module

    monkeypatch.setattr(auth, "PBKDF2_ITERATIONS", 1000)
    store = auth.UserStore(tmp_path_factory.mktemp("web_users") / "users.json")
    for role in auth.ROLES:
        store.create(f"user_{role}", TEST_PASSWORD, role)
    monkeypatch.setattr(main_module, "user_store", store)
    monkeypatch.setattr(main_module, "login_sessions", auth.SessionManager())
    return store


@pytest.fixture
def login_as(web_users):
    """Inicia sesión en un TestClient con el usuario de prueba del rol indicado."""
    def _login(client, role: str = "administrador") -> None:
        response = client.post("/api/auth/login", json={"username": f"user_{role}", "password": TEST_PASSWORD})
        assert response.status_code == 200, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf"]
    return _login


@pytest.fixture
def api_client(monkeypatch, login_as):
    """TestClient con el agente "inicializado" de forma simulada, un SessionStore
    aislado por test (evita fugas de sesiones entre tests vía el singleton de módulo)
    y sesión iniciada como administrador."""
    from fastapi.testclient import TestClient
    from interface.backend import main as main_module
    from interface.backend.api_handlers import ChatHandler, SessionStore

    def fake_initialize_agent(self, max_retries: int = 3):
        self.executor = MagicMock()
        self.executor.invoke.return_value = {
            "messages": [AIMessage(content="respuesta simulada")]
        }
        self.db_connected = True
        self.llm_ready = True
        return True, "Conexión establecida correctamente."

    monkeypatch.setattr(ChatHandler, "initialize_agent", fake_initialize_agent)
    monkeypatch.setattr(main_module.chat_handler, "sessions", SessionStore())

    with TestClient(main_module.app) as client:
        login_as(client)
        yield client
