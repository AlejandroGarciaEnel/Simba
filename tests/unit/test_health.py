"""
tests/unit/test_health.py
Revisión de estado: reglas de diagnóstico, caché e histórico (sin Oracle real).
"""
from datetime import timedelta

import pytest

import db.queries as q
from health import checker
from health.store import HealthStore


@pytest.fixture
def store(tmp_path):
    return HealthStore(tmp_path / "health")


@pytest.fixture
def healthy_db(monkeypatch):
    monkeypatch.setattr(q, "get_cpu_usage", lambda: 20.0)
    monkeypatch.setattr(q, "get_blocked_waits", lambda: [])
    monkeypatch.setattr(q, "get_resource_limits", lambda: [
        {"RESOURCE_NAME": "sessions", "CURRENT_UTILIZATION": 50, "LIMIT_VALUE": "1000"}])
    monkeypatch.setattr(q, "get_tablespace_usage", lambda: [
        {"TABLESPACE_NAME": "USERS", "CONTENTS": "PERMANENT", "USED_PCT": 40}])
    monkeypatch.setattr(q, "get_total_inactive_sessions", lambda: 3)
    monkeypatch.setattr(q, "get_recent_ora_errors", lambda: [])
    monkeypatch.setattr(q, "get_current_wait_events", lambda: [])
    monkeypatch.setattr(q, "get_long_operations", lambda: [])


def test_healthy_database_points_outside_oracle(healthy_db):
    result = checker.run_checks()

    assert result["overall"] == checker.OK
    assert "fuera de Oracle" in result["summary"]


def test_inactive_blocker_is_reported_as_uncommitted_transaction(healthy_db, monkeypatch):
    monkeypatch.setattr(q, "get_blocked_waits", lambda: [{
        "SID_BLOQUEADA": 10, "SID_BLOQUEANTE": 345, "SEGUNDOS_ESPERA": 600,
        "ESTADO_BLOQUEANTE": "INACTIVE", "SEGUNDOS_ULTIMA_LLAMADA": 1320,
        "USUARIO_BLOQUEANTE": "APP", "PROGRAMA_BLOQUEANTE": "x", "MAQUINA_BLOQUEANTE": "m"}])

    result = checker.run_checks()

    assert result["overall"] == checker.CRITICAL
    assert "sin commit" in result["summary"]
    assert "decisión humana" in result["summary"]


def test_failing_check_does_not_abort_the_rest(healthy_db, monkeypatch):
    def denied():
        raise RuntimeError("ORA-00942")
    monkeypatch.setattr(q, "get_tablespace_usage", denied)

    result = checker.run_checks()

    assert result["overall"] == checker.INFO
    assert "tablespaces" in result["summary"]


def test_tablespace_and_limits_thresholds(healthy_db, monkeypatch):
    monkeypatch.setattr(q, "get_tablespace_usage", lambda: [
        {"TABLESPACE_NAME": "TEMP", "CONTENTS": "TEMPORARY", "USED_PCT": 97}])
    monkeypatch.setattr(q, "get_resource_limits", lambda: [
        {"RESOURCE_NAME": "processes", "CURRENT_UTILIZATION": 850, "LIMIT_VALUE": "1000"}])

    result = checker.run_checks()
    areas = {(f["area"], f["severity"]) for f in result["findings"]}

    assert ("TEMP", checker.CRITICAL) in areas
    assert ("Conexiones", checker.WARNING) in areas


def test_cache_reuses_recent_check_and_logs_every_request(healthy_db, store, monkeypatch):
    first = checker.get_health("ana", store=store)
    second = checker.get_health("luis", store=store)
    forced = checker.get_health("luis", force_refresh=True, store=store)

    assert first["from_cache"] is False
    assert second["from_cache"] is True and second["id"] == first["id"]
    assert forced["from_cache"] is False and forced["id"] != first["id"]
    history = store.history()
    assert [h["requested_by"] for h in history] == ["luis", "luis", "ana"]
    assert [h["from_cache"] for h in history] == [False, True, False]


def test_expired_cache_runs_a_new_check(healthy_db, store, monkeypatch):
    checker.get_health("ana", store=store)
    monkeypatch.setattr(checker, "cache_ttl", lambda: timedelta(seconds=0))

    again = checker.get_health("ana", store=store)

    assert again["from_cache"] is False


def test_format_health_shows_time_and_origin(healthy_db, store):
    text = checker.format_health(checker.get_health("ana", store=store))

    assert "recién ejecutada" in text and "UTC" in text
