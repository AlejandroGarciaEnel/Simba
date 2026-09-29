"""
tests/unit/test_api_handlers.py
Pruebas de ChatHandler: BD y LLM deben fallar/recuperarse de forma independiente.
"""
from unittest.mock import MagicMock

from interface.backend.api_handlers import ChatHandler


def test_initialize_agent_keeps_db_connected_when_llm_build_fails(monkeypatch):
    monkeypatch.setattr(
        "interface.backend.api_handlers.get_connection", lambda: MagicMock()
    )
    monkeypatch.setattr(
        "interface.backend.api_handlers.build_agent",
        MagicMock(side_effect=RuntimeError("boom")),
    )

    handler = ChatHandler()
    success, message = handler.initialize_agent(max_retries=1)

    assert success is False
    assert handler.db_connected is True
    assert handler.connection_error is None
    assert handler.llm_ready is False
    assert handler.llm_error is not None and "boom" in handler.llm_error
    assert handler.executor is None
    assert "Base de datos conectada" in message


def test_initialize_agent_short_circuits_llm_when_db_fails(monkeypatch):
    monkeypatch.setattr(
        "interface.backend.api_handlers.get_connection",
        MagicMock(side_effect=RuntimeError("no db")),
    )
    build_agent_mock = MagicMock()
    monkeypatch.setattr("interface.backend.api_handlers.build_agent", build_agent_mock)

    handler = ChatHandler()
    success, _ = handler.initialize_agent(max_retries=1)

    assert success is False
    assert handler.db_connected is False
    assert handler.llm_ready is False
    build_agent_mock.assert_not_called()


def test_reset_connection_only_retries_failing_component(monkeypatch):
    monkeypatch.setattr(
        "interface.backend.api_handlers.get_connection", lambda: MagicMock()
    )
    build_agent_calls = []

    def fake_build_agent():
        build_agent_calls.append(1)
        if len(build_agent_calls) == 1:
            raise RuntimeError("llm down")
        return MagicMock()

    monkeypatch.setattr("interface.backend.api_handlers.build_agent", fake_build_agent)

    handler = ChatHandler()
    handler.initialize_agent(max_retries=1)
    assert handler.db_connected is True
    assert handler.llm_ready is False

    success, _ = handler.reset_connection()

    assert success is True
    assert handler.llm_ready is True
    # la BD nunca se reconecta porque ya estaba conectada (solo se reintentó el LLM)
    assert len(build_agent_calls) == 2
