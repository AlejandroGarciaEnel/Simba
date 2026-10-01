from pathlib import Path

import agent.tools as tools
from report.awr_analyzer import summarize_awr_report


def test_summarize_awr_report_extracts_db_summary_and_findings():
    summary = summarize_awr_report(Path("docs/awr_example.html"))

    assert "CRAGU4E" in summary
    assert "Top SQL Statements" in summary
    assert "2 instancias" in summary


def test_summarize_awr_report_reports_db_time_in_minutes():
    summary = summarize_awr_report(Path("docs/awr_example.html"))

    assert "Tiempo DB: 5,326.45 min" in summary


def test_summarize_awr_report_conclusion_follows_real_findings():
    summary = summarize_awr_report(Path("docs/awr_example.html"))

    assert 'mayor impacto es "Top SQL Statements"' in summary
    assert "RF002 y RF010" in summary


def test_summarize_awr_report_without_addm_findings_does_not_invent_them(tmp_path):
    report = tmp_path / "awr.html"
    report.write_text("<html><head><title>AWR Report for DB: TESTDB</title></head><body>WORKLOAD REPOSITORY</body></html>")

    summary = summarize_awr_report(report)

    assert "no incluye hallazgos ADDM" in summary
    assert "Top SQL Statements" not in summary
    assert "PL/SQL" not in summary


def test_analyze_awr_report_tool_returns_summary():
    result = tools.analyze_awr_report.invoke({"file_path": "docs/awr_example.html"})

    assert "CRAGU4E" in result
    assert "Resumen AWR" in result
