import datetime as dt

from query_reports import awr_weekly as aw


def _rows(day, hours):
    return [{"instancia": 1, "fin": f"{day}T{h:02d}:00:05"} for h in hours]


def test_dia_completo_ok_y_hueco_warn():
    now = dt.datetime(2026, 10, 14, 19, 0)  # miércoles
    ok = aw.analyze_snapshots(_rows("2026-10-14", range(8, 19)), 60, now)
    assert ok["days"][-1]["status"] == "ok"
    gap = aw.analyze_snapshots(_rows("2026-10-14", [8, 9, 14, 15, 16, 17, 18]), 60, now)
    assert gap["days"][-1]["status"] == "warn"


def test_sin_snapshots_critico_y_antes_de_horario_pendiente():
    assert aw.analyze_snapshots([], 60, dt.datetime(2026, 10, 14, 19, 0))["days"][-1]["status"] == "crit"
    assert aw.analyze_snapshots([], 60, dt.datetime(2026, 10, 14, 7, 0))["days"][-1]["status"] == "pending"
    assert aw.analyze_snapshots([], 60, dt.datetime(2026, 10, 17, 12, 0))["days"][-1]["status"] == "off"


def test_nombre_prioridad_y_cron():
    assert aw.week_filename(dt.date(2026, 10, 12)) == "PRAGU4E_Informe_Semana_12Oct_16Oct.xlsx"
    assert [aw.priority(x) for x in (9, 3, 1.5, 0.1)] == ["CRÍTICA", "ALTA", "MEDIA", "BAJA"]
    assert aw.last_due(dt.datetime(2026, 10, 16, 15, 0), 4, 16) == dt.date(2026, 10, 5)
    assert aw.last_due(dt.datetime(2026, 10, 16, 16, 0), 4, 16) == dt.date(2026, 10, 12)


def test_generar_no_sobrescribe_y_lo_lee_el_tablero(tmp_path, monkeypatch):
    from query_reports import advisor

    monkeypatch.setenv("SIMBA_WEEKLY_OUTPUT_DIR", str(tmp_path))
    top = [{"SQL_ID": "abc123", "CPU_H": 5.0, "PCT_CPU": 12.0, "EJECUCIONES": 10, "DIAS": 5, "GETS_EJEC": 3,
            "GETS_FILA": 2, "PLANES": 1, "ESQUEMA": "ENET", "SQL_TEXT": "select 1"}]
    daily = [{"SQL_ID": "abc123", "DIA": "2026-10-12", "CPU_S": 100}]
    fetch = (lambda *a: top, lambda *a: daily)
    r1 = aw.generate_weekly(dt.date(2026, 10, 12), fetch=fetch)
    r2 = aw.generate_weekly(dt.date(2026, 10, 12), fetch=fetch)
    assert (r1["status"], r2["status"]) == ("ok", "exists")
    assert len(list(tmp_path.glob("*.xlsx"))) == 1
    assert advisor.read_weekly_reports(tmp_path)
