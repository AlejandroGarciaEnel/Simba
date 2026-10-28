"""
tests/unit/test_awr_followup.py
Seguimiento en vivo del análisis AWR (RF021): lista blanca, comparación de SQL IDs y HTML ampliado.
"""
from pathlib import Path

import pytest

import db.queries as q
import report.awr_followup as followup
from report.awr_analyzer import AwrAnalysis, AwrSql, FollowupArea, parse_awr_report

EXAMPLE = Path("docs/awr_example.html")


def make_analysis(findings=(), top_sql=()):
    return AwrAnalysis(
        db_name="TESTDB", snapshot="1-2", instance_count="1", host_count="1",
        db_time="10", elapsed="60", avg_cpu_busy=1.0, findings=tuple(findings), top_sql=tuple(top_sql),
    )


@pytest.fixture
def live_db(monkeypatch):
    monkeypatch.setattr("report.awr_followup.get_connection", lambda: object())


def test_parse_extracts_top_sql_from_example():
    analysis = parse_awr_report(EXAMPLE)

    assert len(analysis.top_sql) == 5
    first = analysis.top_sql[0]
    assert (first.sql_id, first.elapsed_s, first.execs) == ("8p7xxjf1m0cdh", "14,838.32", "22")
    assert first.pct_db_time == "4.64"


def test_parse_discards_sql_ids_with_invalid_format(tmp_path):
    report = tmp_path / "awr.html"
    report.write_text(
        '<html><head><title>DB: X</title></head><body>WORKLOAD REPOSITORY'
        '<h3 class="awr">SQL ordered by Elapsed Time</h3><table><tr>'
        '<td scope="row" class="awrc"><a class="awr" href="#x">1; DROP TABLE users</a></td></tr>'
        '<tr><td scope="row" class="awrc"><a class="awr" href="#y">abcdefghij123</a></td>'
        '<td headers="Total Elapsed(s)">12.5</td></tr></table></body></html>'
    )

    top = parse_awr_report(report).top_sql

    assert [item.sql_id for item in top] == ["abcdefghij123"]
    assert top[0].elapsed_s == "12.5" and top[0].execs == "N/D"


def test_run_followup_without_database_degrades_gracefully():
    result = followup.run_followup(make_analysis(findings=["CPU Usage"]))

    assert result.available is False
    assert "sin conexión" in result.render_text()


def test_run_followup_executes_actions_of_matching_areas(mocker, live_db):
    cpu = mocker.patch.object(q, "get_cpu_usage", return_value=42.5)
    mocker.patch.object(q, "get_top_cpu_sessions", return_value=[])
    mocker.patch.object(q, "get_blocking_sessions", return_value=[])
    mocker.patch.object(q, "get_table_lock_detection", return_value=[])

    result = followup.run_followup(make_analysis(findings=["CPU Usage", "Row Lock contention"]))

    text = result.render_text()
    assert result.available
    cpu.assert_called_once()
    assert "42.50%" in text
    assert "No se detectaron sesiones bloqueantes" in text
    assert "consumo de CPU" in text and "bloqueos y contención" in text


def test_run_followup_without_findings_uses_generic_actions(mocker, live_db):
    summary = mocker.patch.object(q, "get_database_summary", return_value=[])
    mocker.patch.object(q, "get_metrics", return_value=[])
    mocker.patch.object(q, "get_latency_wait_metrics", return_value=[])

    result = followup.run_followup(make_analysis())

    summary.assert_called_once()
    assert "estado general de la base de datos" in result.render_text()


def test_run_followup_keeps_going_after_partial_failure(mocker, live_db):
    mocker.patch.object(q, "get_cpu_usage", side_effect=RuntimeError("ORA-secreto"))
    sessions = mocker.patch.object(q, "get_top_cpu_sessions", return_value=[])

    result = followup.run_followup(make_analysis(findings=["CPU Usage"]))

    text = result.render_text()
    sessions.assert_called_once()
    assert "No se pudo ejecutar (RuntimeError)" in text
    assert "ORA-secreto" not in text
    assert "1 con error" in result.conclusion


def test_run_followup_ignores_actions_outside_whitelist(monkeypatch, live_db):
    evil = FollowupArea(("cpu",), "evil", "RF000", ("os.system", "__import__"))
    monkeypatch.setattr("report.awr_analyzer._FINDING_AREAS", [evil])

    result = followup.run_followup(make_analysis(findings=["CPU Usage"]))

    assert result.sections == []


def test_run_followup_stops_at_action_limit(mocker, live_db, monkeypatch):
    monkeypatch.setattr(followup, "MAX_ACTIONS", 1)
    mocker.patch.object(q, "get_cpu_usage", return_value=1.0)
    sessions = mocker.patch.object(q, "get_top_cpu_sessions", return_value=[])

    result = followup.run_followup(make_analysis(findings=["CPU Usage"]))

    sessions.assert_not_called()
    assert "seguimiento parcial" in result.render_text()


def test_compare_top_sql_classifies_live_state(mocker, live_db):
    mocker.patch.object(q, "get_top_cpu_queries", return_value=[{"SQL_ID": "aaaaaaaaaaaaa"}])
    mocker.patch.object(
        q, "get_sql_info_by_sql_id",
        side_effect=lambda sql_id: [{"SQL_ID": sql_id}] if sql_id == "bbbbbbbbbbbbb" else [],
    )
    top_sql = [AwrSql(i * 13, "10", "1", "1.0") for i in "abc"]

    result = followup.run_followup(make_analysis(top_sql=top_sql))

    text = result.render_text()
    assert "En el top de CPU actual" in text
    assert "Con 1 sesión(es) ahora" in text
    assert "No visible en vivo" in text
    assert "2 de 3 SQL del AWR siguen activas" in result.conclusion


def test_analyze_with_followup_without_followup_returns_only_summary():
    outcome = followup.analyze_with_followup(EXAMPLE, followup=False)

    assert "CRAGU4E" in outcome.summary
    assert outcome.followup == ""
    assert outcome.message == outcome.summary


def test_analyze_with_followup_returns_followup_when_database_available(mocker, live_db):
    mocker.patch.object(q, "get_top_cpu_queries", return_value=[])
    mocker.patch.object(q, "get_sql_info_by_sql_id", return_value=[])

    outcome = followup.analyze_with_followup(EXAMPLE)

    assert "8p7xxjf1m0cdh" in outcome.followup and "14,838.32" in outcome.followup
    assert outcome.message == f"{outcome.summary}\n\n{outcome.followup}"


def test_analyze_with_followup_without_database_returns_notice():
    outcome = followup.analyze_with_followup(EXAMPLE)

    assert "sin conexión" in outcome.followup
    assert "CRAGU4E" in outcome.summary


@pytest.mark.parametrize("value, expected", [("", True), ("true", True), ("false", False), ("0", False), ("No", False)])
def test_followup_enabled_flag(monkeypatch, value, expected):
    monkeypatch.setenv("SIMBA_AWR_FOLLOWUP", value) if value else monkeypatch.delenv("SIMBA_AWR_FOLLOWUP", raising=False)

    assert followup.followup_enabled() is expected
