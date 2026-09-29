"""
tests/api/test_main.py
Pruebas de la API FastAPI (interface/backend/main.py) sin BD ni LLM reales.
"""


def test_health_endpoint_reports_initialized_state(api_client):
    response = api_client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db_connected"] is True


def test_chat_without_session_header_creates_new_session(api_client):
    response = api_client.post("/api/chat", json={"message": "¿Cuánta CPU se usa?"})

    assert response.status_code == 200
    assert response.headers.get("X-Session-Id")
    assert response.json()["success"] is True


def test_chat_rejects_empty_message(api_client):
    response = api_client.post("/api/chat", json={"message": "   "})

    assert response.status_code == 400


def test_chat_starts_fresh_session_after_ttl_expiry(api_client, monkeypatch):
    from datetime import datetime, timedelta
    from interface.backend import main as main_module

    first = api_client.post("/api/chat", json={"message": "primer mensaje"})
    session_id = first.headers["X-Session-Id"]

    # Simula que la sesión quedó inactiva más de 30 min desde la última llamada
    session = main_module.chat_handler.sessions._sessions[session_id]
    session["last_activity"] = datetime.utcnow() - timedelta(minutes=31)

    response = api_client.post(
        "/api/chat",
        json={"message": "mensaje tras expirar"},
        headers={"X-Session-Id": session_id},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    # la sesión expirada se sustituye por una nueva, sin arrastrar el historial previo
    new_session_id = response.headers["X-Session-Id"]
    assert new_session_id != session_id

    history = api_client.get("/api/chat-history", headers={"X-Session-Id": new_session_id}).json()
    assert not any("primer mensaje" in m["content"] for m in history["history"])


def test_chat_history_is_isolated_between_sessions(api_client):
    first = api_client.post("/api/chat", json={"message": "hola desde sesion A"})
    session_a = first.headers["X-Session-Id"]

    second = api_client.post(
        "/api/chat",
        json={"message": "hola desde sesion B"},
        headers={"X-Session-Id": "id-invalido-o-de-otra-sesion"},
    )
    session_b = second.headers["X-Session-Id"]

    assert session_a != session_b

    history_a = api_client.get("/api/chat-history", headers={"X-Session-Id": session_a}).json()
    history_b = api_client.get("/api/chat-history", headers={"X-Session-Id": session_b}).json()

    assert any("sesion A" in m["content"] for m in history_a["history"])
    assert not any("sesion A" in m["content"] for m in history_b["history"])


def test_clear_history_only_affects_own_session(api_client):
    chat_response = api_client.post("/api/chat", json={"message": "mensaje a limpiar"})
    session_id = chat_response.headers["X-Session-Id"]

    other_response = api_client.post("/api/chat", json={"message": "mensaje de otra sesion"})
    other_session_id = other_response.headers["X-Session-Id"]

    api_client.post("/api/clear-history", headers={"X-Session-Id": session_id})

    history_cleared = api_client.get(
        "/api/chat-history", headers={"X-Session-Id": session_id}
    ).json()
    history_untouched = api_client.get(
        "/api/chat-history", headers={"X-Session-Id": other_session_id}
    ).json()

    assert history_cleared["history"] == []
    assert len(history_untouched["history"]) > 0


def test_download_report_rejects_invalid_filename(api_client):
    response = api_client.get("/api/download-report/../secrets.txt")

    assert response.status_code in (400, 404)
