"""
tests/unit/test_connection.py
Pruebas del singleton de conexión Oracle: debe recuperarse si la sesión se cae.
"""
from unittest.mock import MagicMock

import pytest

import db.connection as connection


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    monkeypatch.setattr(connection, "_connection", None)


def test_get_connection_reuses_live_connection(monkeypatch):
    live = MagicMock()
    create = MagicMock(return_value=live)
    monkeypatch.setattr(connection, "_create_connection", create)

    assert connection.get_connection() is live
    assert connection.get_connection() is live
    create.assert_called_once()


def test_get_connection_recreates_dropped_connection(monkeypatch):
    dropped = MagicMock()
    dropped.ping.side_effect = Exception("DPI-1080: connection was closed by ORA-3113")
    fresh = MagicMock()
    monkeypatch.setattr(connection, "_connection", dropped)
    monkeypatch.setattr(connection, "_create_connection", MagicMock(return_value=fresh))

    assert connection.get_connection() is fresh
    dropped.close.assert_called_once()
