import datetime as dt

from query_reports.advisor import build_recommendations, format_query_improvements

MONDAY = dt.date(2026, 10, 12)


def _row(cpu=10.0, sql="select * from t where a = :1", ejec=1000, gets=5000, gets_fila=10, planes=1):
    return {"prioridad": "ALTA", "cpu_h": cpu, "pct_cpu": 2.0, "ejecuciones": ejec, "dias": 5,
            "gets_ejec": gets, "gets_fila": gets_fila, "planes": planes, "esquema": "APP",
            "sql_text": sql, "notas": ""}


def _week(monday, rows):
    return {"monday": monday, "label": str(monday), "file": "informe.xlsx", "rows": rows}


def _kinds(result, sid):
    item = next(i for i in result["items"] if i["sql_id"] == sid)
    return [f["tipo"] for f in item["hallazgos"]]


def test_new_sql_without_tracking_is_flagged():
    tracking = {"bbbbbbbbbbbbb": {"ESTADO": "Pendiente", "SEMANAS EN TOP": 1}}
    result = build_recommendations([_week(MONDAY, {"aaaaaaaaaaaaa": _row(cpu=20)})], tracking)
    assert _kinds(result, "aaaaaaaaaaaaa") == ["nueva_sin_seguimiento"]
    assert result["kpis"]["sin_seguimiento"] == 1
    assert result["kpis"]["cpu_sin_seguimiento_h"] == 20


def test_completed_still_in_top_only_after_a_full_week():
    tracking = {
        "aaaaaaaaaaaaa": {"ESTADO": "Completado", "CPU H/SEM (MEDIA)": 40, "FECHA COMPLETADO": dt.date(2026, 10, 1)},
        "ccccccccccccc": {"ESTADO": "Completado", "CPU H/SEM (MEDIA)": 40, "FECHA COMPLETADO": dt.date(2026, 10, 14)},
    }
    rows = {"aaaaaaaaaaaaa": _row(cpu=35), "ccccccccccccc": _row(cpu=35)}
    result = build_recommendations([_week(MONDAY, rows)], tracking)
    assert _kinds(result, "aaaaaaaaaaaaa") == ["completada_reaparece"]
    assert all(i["sql_id"] != "ccccccccccccc" for i in result["items"])
    assert result["kpis"]["completadas_que_reaparecen"] == 1


def test_stalled_and_technical_hints():
    tracking = {"aaaaaaaaaaaaa": {"ESTADO": "En curso", "SEMANAS EN TOP": 5, "PERSONA": "Ana"}}
    rows = {"aaaaaaaaaaaaa": _row(planes=4, gets_fila=50_000, ejec=200_000, gets=1_000)}
    result = build_recommendations([_week(MONDAY, rows)], tracking)
    assert _kinds(result, "aaaaaaaaaaaaa") == ["estancada", "planes_multiples", "lecturas_por_fila",
                                               "muchas_ejecuciones"]


def test_plsql_call_skips_read_hints():
    tracking = {"aaaaaaaaaaaaa": {"ESTADO": "Pendiente", "SEMANAS EN TOP": 1}}
    rows = {"aaaaaaaaaaaaa": _row(sql="BEGIN pkg.run(:1); END;", gets_fila=99_999)}
    result = build_recommendations([_week(MONDAY, rows)], tracking)
    assert _kinds(result, "aaaaaaaaaaaaa") == ["plsql"]


def test_completed_out_of_top_without_measurements():
    tracking = {"ddddddddddddd": {"ESTADO": "Completado", "COMPROBACIÓN": "⚠ Faltan tiempos (TBD)"}}
    result = build_recommendations([_week(MONDAY, {"aaaaaaaaaaaaa": _row()})], tracking)
    assert _kinds(result, "ddddddddddddd") == ["completada_sin_medir"]
    assert result["kpis"]["completadas_fuera_del_top"] == 1


def test_text_ends_with_functional_note_and_filters_by_sql_id():
    tracking = {"bbbbbbbbbbbbb": {"ESTADO": "Pendiente"}}
    result = build_recommendations([_week(MONDAY, {"aaaaaaaaaaaaa": _row()})], tracking)
    text = format_query_improvements(result, sql_id="aaaaaaaaaaaaa")
    assert "aaaaaaaaaaaaa" in text
    assert "equipo funcional" in text
