"""
tests/unit/test_tools.py
Pruebas de agent/tools.py mockeando db.queries (sin BD real ni LangChain runtime).
"""
import agent.tools as tools


def test_get_cpu_usage_tool_formats_percentage(mocker):
    mocker.patch.object(tools.q, "get_cpu_usage", return_value=42.5)

    result = tools.get_cpu_usage.invoke({})

    assert result == "CPU actual de la base de datos: 42.50%"


def test_get_top_cpu_queries_tool_renders_table(mocker):
    mocker.patch.object(
        tools.q,
        "get_top_cpu_queries",
        return_value=[
            {"USUARIO": "SYS", "EJECUCIONES": 10, "PCT_CPU": 55.5, "CPU_TIME": 1234, "SQL": "SELECT 1"}
        ],
    )

    result = tools.get_top_cpu_queries.invoke({"limit": 5})

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
