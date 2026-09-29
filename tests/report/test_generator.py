"""
tests/report/test_generator.py
Prueba el generador de informe HTML mockeando db.queries y redirigiendo la
carpeta de salida a un directorio temporal (no debe escribir en ./reports real).
"""
import report.generator as generator


LIST_RETURNING_QUERIES = [
    "get_metrics",
    "get_sga_info",
    "get_latency_wait_metrics",
    "get_users_with_active_sessions",
    "get_users_with_inactive_sessions",
    "get_blocking_sessions",
    "get_blocking_sql",
    "get_table_lock_detection",
    "get_sessions_by_program_and_machine",
    "get_sessions_by_user",
    "get_sessions_by_module",
    "detect_pooling",
    "get_top_table_sizes",
    "get_session_user_metrics",
    "get_sessions_by_user_status",
]

COUNT_RETURNING_QUERIES = [
    "get_total_sessions",
    "get_total_active_sessions",
    "get_total_inactive_sessions",
    "get_total_blocking_sql",
    "get_total_blocked_sessions",
]


def _mock_all_queries(mocker, cpu_pct: float = 42.5) -> None:
    mocker.patch.object(generator.q, "get_cpu_usage", return_value=cpu_pct)
    for name in LIST_RETURNING_QUERIES:
        mocker.patch.object(generator.q, name, return_value=[])
    for name in COUNT_RETURNING_QUERIES:
        mocker.patch.object(generator.q, name, return_value=0)


def test_generate_creates_html_report_in_reports_dir(mocker, tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "REPORTS_DIR", tmp_path)
    _mock_all_queries(mocker, cpu_pct=42.5)

    output_path = generator.generate()

    from pathlib import Path
    report_file = Path(output_path)
    assert report_file.exists()
    assert report_file.parent == tmp_path
    assert report_file.name.startswith("dbCheck_")
    assert report_file.suffix == ".html"

    html = report_file.read_text(encoding="utf-8")
    assert "42.50%" in html


def test_generate_marks_cpu_status_red_when_high(mocker, tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "REPORTS_DIR", tmp_path)
    _mock_all_queries(mocker, cpu_pct=95.0)

    output_path = generator.generate()

    html = open(output_path, encoding="utf-8").read()
    assert "Rojo" in html
