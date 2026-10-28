"""
tests/unit/test_tools.py
Pruebas de agent/tools.py mockeando db.queries (sin BD real ni LangChain runtime).
"""
import agent.tools as tools
from report.awr_followup import AwrOutcome

def test_get_cpu_usage_tool_formats_percentage(mocker):
    mocker.patch.object(tools.q, "get_cpu_usage", return_value=42.5)

    result = tools.get_cpu_usage.invoke({})

    assert result == "CPU actual de la base de datos: 42.50%"


def test_get_top_cpu_queries_tool_renders_table(mocker):
    mocker.patch.object(
        tools.q,
        "get_top_cpu_queries",
        return_value=[
            {"SQL_ID": "abc123xyz", "USUARIO": "SYS", "EJECUCIONES": 10, "PCT_CPU": 55.5, "CPU_TIME": 1234, "SQL": "SELECT 1"}
        ],
    )

    result = tools.get_top_cpu_queries.invoke({"limit": 5})

    assert "SQL ID" in result
    assert "abc123xyz" in result
    assert "SYS" in result
    assert "SELECT 1" in result


def test_get_top_cpu_queries_tool_handles_empty_result(mocker):
    mocker.patch.object(tools.q, "get_top_cpu_queries", return_value=[])

    result = tools.get_top_cpu_queries.invoke({"limit": 5})

    assert result == "No se encontraron queries con consumo de CPU significativo."


def test_get_total_inactive_sessions_tool(mocker):
    mocker.patch.object(tools.q, "get_total_inactive_sessions", return_value=3)

    result = tools.get_total_inactive_sessions.invoke({})

    assert result == "Total de sesiones inactivas (>30 min): 3"


def test_get_inactive_sessions_by_user_tool_without_match(mocker):
    mocker.patch.object(tools.q, "get_inactive_sessions_by_user", return_value=[])

    result = tools.get_inactive_sessions_by_user.invoke({"username": "APP_USER", "limit": 5})

    assert "APP_USER" in result


def test_generate_report_tool_returns_generated_filename(mocker):
    mocker.patch("report.generator.generate", return_value="/tmp/reports/dbCheck_01-01-2026_00-00.html")

    result = tools.generate_report.invoke({})

    assert "dbCheck_01-01-2026_00-00.html" in result


def test_analyze_awr_report_rejects_paths_outside_allowed_dirs(mocker):
    analyze = mocker.patch.object(tools, "analyze_with_followup")

    for path in ("../.env", "C:/Windows/win.ini", "awr/../.env", "docs/example.html"):
        result = tools.analyze_awr_report.invoke({"file_path": path})
        assert "no permitida" in result

    analyze.assert_not_called()


def test_analyze_awr_report_accepts_uploaded_filename(mocker, tmp_path, monkeypatch):
    monkeypatch.setattr("report.awr_analyzer.AWR_DIR", tmp_path)
    analyze = mocker.patch.object(tools, "analyze_with_followup", return_value=AwrOutcome("resumen"))

    result = tools.analyze_awr_report.invoke({"file_path": "awr_01-01-2026_00-00-00_abcd.html"})

    assert result == "resumen"
    analyze.assert_called_once_with((tmp_path / "awr_01-01-2026_00-00-00_abcd.html").resolve())


def test_analyze_awr_report_accepts_default_example(mocker):
    analyze = mocker.patch.object(tools, "analyze_with_followup", return_value=AwrOutcome("resumen"))

    assert tools.analyze_awr_report.invoke({}) == "resumen"
    analyze.assert_called_once()


def test_analyze_awr_report_appends_followup_to_summary(mocker):
    mocker.patch.object(
        tools, "analyze_with_followup", return_value=AwrOutcome("resumen", "contraste")
    )

    result = tools.analyze_awr_report.invoke({})

    assert result == "resumen\n\ncontraste"
