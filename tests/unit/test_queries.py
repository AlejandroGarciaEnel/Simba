"""
tests/unit/test_queries.py
Pruebas de db/queries.py con conexión Oracle simulada (una por RF representativa).
"""
import db.queries as q
from tests.conftest import set_query_result


def test_get_cpu_usage_returns_rounded_percentage(mock_db_connection, fake_cursor):
    set_query_result(fake_cursor, ["CPU_PCT"], [(42.5,)])

    result = q.get_cpu_usage()

    assert result == 42.5


def test_get_cpu_usage_defaults_to_zero_when_null(mock_db_connection, fake_cursor):
    set_query_result(fake_cursor, ["CPU_PCT"], [(None,)])

    result = q.get_cpu_usage()

    assert result == 0.0


def test_get_top_cpu_queries_maps_columns(mock_db_connection, fake_cursor):
    set_query_result(
        fake_cursor,
        ["USUARIO", "EJECUCIONES", "PCT_CPU", "CPU_TIME", "SQL"],
        [("SYS", 10, 55.5, 1234, "SELECT 1 FROM DUAL")],
    )

    rows = q.get_top_cpu_queries(limit=5)

    assert rows == [
        {
            "USUARIO": "SYS",
            "EJECUCIONES": 10,
            "PCT_CPU": 55.5,
            "CPU_TIME": 1234,
            "SQL": "SELECT 1 FROM DUAL",
        }
    ]


def test_get_top_cpu_queries_empty_result(mock_db_connection, fake_cursor):
    set_query_result(fake_cursor, ["USUARIO", "EJECUCIONES", "PCT_CPU", "CPU_TIME", "SQL"], [])

    rows = q.get_top_cpu_queries()

    assert rows == []


def test_get_total_inactive_sessions(mock_db_connection, fake_cursor):
    set_query_result(fake_cursor, ["TOTAL_INACTIVAS"], [(7,)])

    total = q.get_total_inactive_sessions()

    assert total == 7


def test_get_total_inactive_sessions_by_user_without_username_short_circuits(
    mock_db_connection, fake_cursor
):
    total = q.get_total_inactive_sessions_by_user("")

    assert total == 0
    fake_cursor.execute.assert_not_called()


def test_get_blocking_sessions_maps_columns(mock_db_connection, fake_cursor):
    set_query_result(
        fake_cursor,
        ["SID", "SERIAL", "USUARIO", "MACHINE"],
        [(101, 5001, "APP_USER", "srv-app-01")],
    )

    rows = q.get_blocking_sessions(limit=5)

    assert rows == [
        {"SID": 101, "SERIAL": 5001, "USUARIO": "APP_USER", "MACHINE": "srv-app-01"}
    ]
