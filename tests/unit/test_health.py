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
    monkeypatch.setattr(q, "get_root_blockers", lambda: [])
    monkeypatch.setattr(q, "get_resource_limits", lambda: [
        {"RESOURCE_NAME": "sessions", "CURRENT_UTILIZATION": 50, "LIMIT_VALUE": "1000"}])
    monkeypatch.setattr(q, "get_tablespace_usage", lambda: [
        {"TABLESPACE_NAME": "USERS", "CONTENTS": "PERMANENT", "USED_PCT": 40}])
    monkeypatch.setattr(q, "get_cluster_inactive_sessions", lambda: 3)
    monkeypatch.setattr(q, "get_recent_problems", lambda: [])
    monkeypatch.setattr(q, "get_current_wait_events", lambda: [])
    monkeypatch.setattr(q, "get_long_operations", lambda: [])


def test_healthy_database_points_outside_oracle(healthy_db):
    result = checker.run_checks()

    assert result["overall"] == checker.OK
    assert "fuera de Oracle" in result["summary"]


def test_every_blocking_session_is_reported_with_its_owner(healthy_db, monkeypatch):
    monkeypatch.setattr(q, "get_root_blockers", lambda: [
        {"INSTANCIA": 1, "SID": 345, "SERIAL": 991, "USUARIO": "APP", "USUARIO_SO": "jboss", "MAQUINA": "srv01",
         "PROGRAMA": "JDBC", "MODULO": "facturacion", "ESTADO": "INACTIVE", "SEGUNDOS_ULTIMA_LLAMADA": 1320,
         "SQL_ID": "abc123", "TIPO_SQL": "última ejecutada", "SQL_TEXTO": "UPDATE pedidos SET ...",
         "SESIONES_BLOQUEADAS": 4, "SEGUNDOS_ESPERA": 600, "EVENTO": "enq: TX - row lock contention",
         "OBJETO": "APP.PEDIDOS"},
        {"INSTANCIA": 2, "SID": 77, "SERIAL": 5, "USUARIO": "BATCH", "MAQUINA": "srv02", "PROGRAMA": "sqlplus",
         "ESTADO": "ACTIVE", "SESIONES_BLOQUEADAS": 1, "SEGUNDOS_ESPERA": 20, "SQL_ID": "def456",
         "TIPO_SQL": "en ejecución"},
    ])

    result = checker.run_checks()
    blocking = next(f for f in result["findings"] if f["area"] == "Bloqueos")

    assert result["overall"] == checker.CRITICAL
    assert [d["sid_serial"] for d in blocking["details"]] == ["345,991", "77,5"]
    assert "5 sesión(es) bloqueada(s) por 2" in blocking["message"]
    assert "srv01" in result["summary"] and "APP.PEDIDOS" in result["summary"] and "srv02" in result["summary"]
    assert "sin commit" in result["summary"]
    assert checker.FUNCTIONAL_NOTE in result["summary"]


def test_missing_recommendations_file_does_not_break_the_check(healthy_db, monkeypatch, tmp_path):
    monkeypatch.setattr(checker, "RECOMMENDATIONS_FILE", tmp_path / "no_existe.json")
    checker._recommendations.cache_clear()
    monkeypatch.setattr(q, "get_cpu_usage", lambda: 90.0)

    result = checker.run_checks()
    checker._recommendations.cache_clear()

    assert result["overall"] == checker.CRITICAL
    assert checker.FUNCTIONAL_NOTE in result["summary"]


def test_every_recommendation_key_used_in_code_exists_in_json():
    import re
    source = open(checker.__file__, encoding="utf-8").read()
    used = set(re.findall(r'"((?:bloqueo|cpu|conexiones|espacio|sesiones|errores)_\w+)"', source))

    assert used <= set(checker._recommendations())


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


def test_agent_tool_ignores_force_refresh_when_role_cannot_force(monkeypatch):
    from agent.tools import check_database_health

    calls = []
    monkeypatch.setattr(checker, "get_health",
                        lambda requested_by="anonimo", force_refresh=False: calls.append((requested_by, force_refresh))
                        or {"from_cache": True, "created_at": "x", "overall": "OK", "summary": "", "findings": []})
    checker.REQUESTER.set("user_consulta")
    checker.CAN_FORCE_REFRESH.set(False)
    try:
        check_database_health.invoke({"force_refresh": True})
    finally:
        checker.REQUESTER.set("anonimo")
        checker.CAN_FORCE_REFRESH.set(True)
    assert calls == [("user_consulta", False)]


def test_recurring_oracle_problem_is_not_treated_as_new(healthy_db, monkeypatch):
    monkeypatch.setattr(q, "get_recent_problems", lambda: [
        {"PROBLEMA": "ORA 600 [20084]", "PRIMERA_VEZ": "2026-04-13 16:28:15", "DIAS_DESDE_PRIMERA": 210},
    ])
    errors = [f for f in checker.run_checks()["findings"] if f["area"] == "Errores"]
    assert [f["severity"] for f in errors] == ["WARNING"]
    assert "desde 2026-04-13" in errors[0]["message"]

    monkeypatch.setattr(q, "get_recent_problems", lambda: [
        {"PROBLEMA": "ORA 600 [kcbz]", "PRIMERA_VEZ": "2026-11-10 10:00:00", "DIAS_DESDE_PRIMERA": 0.2},
    ])
    assert checker.run_checks()["overall"] == "CRITICAL"
