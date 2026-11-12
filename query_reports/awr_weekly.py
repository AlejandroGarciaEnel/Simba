"""
query_reports/awr_weekly.py
Vigilancia del AWR y resumen semanal automático (solo SELECT en Oracle).

- analyze_snapshots: ¿se han guardado snapshots AWR en horario laboral cada día?
- generate_weekly: crea el Excel «PRAGU4E_Informe_Semana_*.xlsx» con el mismo formato que los que ya lee el
  tablero de Queries (hojas «Listado Semanal …» y «Evolución CPU diaria»). Nunca sobrescribe uno existente.
- run_if_due / weekly_loop: cada viernes (SIMBA_WEEKLY_DAY/HOUR) genera el de la semana si aún no existe.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("query_reports.awr_weekly")

STATE_FILE = Path(__file__).resolve().parent.parent / "data" / "awr_weekly.json"
DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "informes_semanales"
MONTHS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
WEEKDAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
_lock = threading.Lock()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def settings() -> dict[str, Any]:
    return {
        "work_start": _env_int("SIMBA_AWR_WORK_START", 8),
        "work_end": _env_int("SIMBA_AWR_WORK_END", 18),
        "weekly_enabled": os.environ.get("SIMBA_WEEKLY_ENABLED", "true").strip().lower() not in ("0", "false", "no"),
        "weekly_day": min(max(_env_int("SIMBA_WEEKLY_DAY", 4), 0), 6),
        "weekly_hour": min(max(_env_int("SIMBA_WEEKLY_HOUR", 16), 0), 23),
    }


# ---------- Snapshots en horario laboral ----------
def _parse(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts)


def analyze_snapshots(rows: list[dict[str, Any]], interval_min: float | None, now: dt.datetime, *,
                      work_start: int = 8, work_end: int = 18, days: int = 7) -> dict[str, Any]:
    """Resumen por día e instancia de los snapshots dentro del horario laboral (lun-vie)."""
    interval = float(interval_min or 60)
    tolerance = interval * 1.5
    snaps: dict[int, list[dt.datetime]] = {}
    for r in rows:
        snaps.setdefault(int(r["instancia"]), []).append(_parse(r["fin"]))
    for lst in snaps.values():
        lst.sort()
    instances = sorted(snaps)
    out_days = []
    for back in range(days - 1, -1, -1):
        day = (now - dt.timedelta(days=back)).date()
        start = dt.datetime.combine(day, dt.time(work_start))
        end = dt.datetime.combine(day, dt.time(work_end))
        laborable = day.weekday() < 5
        entry: dict[str, Any] = {"date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()], "laborable": laborable,
                                 "instances": [], "hours": [0] * 24}
        for h in range(24):
            counts = [sum(1 for t in snaps[i] if t.date() == day and t.hour == h) for i in instances]
            entry["hours"][h] = min(counts) if counts else 0
        if not laborable:
            entry.update(status="off", message="No laborable")
        elif now < start:
            entry.update(status="pending", message="Aún no ha empezado el horario laboral")
        else:
            eff_end = min(end, now)
            worst = "ok"
            for i in instances or [None]:
                pts = [t for t in snaps.get(i, []) if start <= t <= eff_end]
                edges = [start] + pts + [eff_end]
                gap = max((b - a).total_seconds() / 60 for a, b in zip(edges, edges[1:]))
                status = "crit" if not pts else ("warn" if gap > tolerance else "ok")
                if status == "crit" or (status == "warn" and worst == "ok"):
                    worst = status
                entry["instances"].append({
                    "instancia": i, "count": len(pts), "max_gap_min": round(gap),
                    "first": pts[0].strftime("%H:%M") if pts else None,
                    "last": pts[-1].strftime("%H:%M") if pts else None, "status": status})
            entry["status"] = worst
            entry["message"] = {"ok": "Snapshots completos en horario laboral",
                                "warn": "Hay huecos mayores de lo esperado",
                                "crit": "Faltan snapshots en horario laboral"}[worst]
        out_days.append(entry)
    last = {i: snaps[i][-1].isoformat(timespec="seconds") for i in instances}
    today = out_days[-1] if out_days else None
    return {"interval_min": interval, "work_start": work_start, "work_end": work_end, "instances": instances,
            "last_snapshot": last, "days": out_days, "today": today["status"] if today else "crit",
            "now": now.isoformat(timespec="seconds")}


# ---------- Informe semanal ----------
def week_bounds(day: dt.date) -> tuple[dt.date, dt.date]:
    monday = day - dt.timedelta(days=day.weekday())
    return monday, monday + dt.timedelta(days=4)


def week_filename(monday: dt.date) -> str:
    fri = monday + dt.timedelta(days=4)
    return f"PRAGU4E_Informe_Semana_{monday.day:02d}{MONTHS[monday.month - 1]}_{fri.day:02d}{MONTHS[fri.month - 1]}.xlsx"


def priority(pct: float | None) -> str:
    pct = pct or 0
    return "CRÍTICA" if pct >= 5 else "ALTA" if pct >= 2 else "MEDIA" if pct >= 1 else "BAJA"


def output_dir() -> Path:
    for name in ("SIMBA_WEEKLY_OUTPUT_DIR", "SIMBA_QUERY_REPORTS_DIR"):
        value = os.environ.get(name, "").strip()
        if value:
            return Path(value).expanduser()
    return DEFAULT_DIR


def _unique(path: Path) -> Path:
    n = 2
    while path.exists():
        path = path.with_name(f"{path.stem}_v{n}{path.suffix}")
        n += 1
    return path


def build_workbook(monday: dt.date, top: list[dict[str, Any]], daily: list[dict[str, Any]]):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    fri = monday + dt.timedelta(days=4)
    label_a = f"{monday.day} {MONTHS[monday.month - 1]}"
    label_b = f"{fri.day} {MONTHS[fri.month - 1]}"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Listado Semanal {monday.day}{MONTHS[monday.month - 1]}-{fri.day}{MONTHS[fri.month - 1]}"
    ws["A1"] = f"PRAGU4E — SQL_IDs Top a Revisar · Semana Lun {label_a} – Vie {label_b} {fri.year}"
    ws["A2"] = "Basado en métricas reales de DBA_HIST (Top por CPU) · generado automáticamente por SIMBA"
    ws["A3"] = "Priorización por CPU total consumida en la semana. La columna NOTAS se rellena a mano en el seguimiento."
    ws["A1"].font = Font(bold=True, size=14)
    head = ["#", "SQL_ID", "Prioridad", "CPU total \n(horas)", "% CPU \nsem", "Ejec. \nsemana", "Días \n(5)",
            "Gets/ejec \n(medio)", "Gets por FILA \n(medio)", "Planes", "Esquema", "SQL_TEXT", "NOTAS  \nANALISIS DE MEJORA"]
    ws.append([])
    ws.append(head)
    for c in ws[5]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F2A44")
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for i, r in enumerate(top, 1):
        pct = float(r.get("pct_cpu") or 0)
        ws.append([i, r["sql_id"], priority(pct), float(r.get("cpu_h") or 0), pct, int(r.get("ejecuciones") or 0),
                   int(r.get("dias") or 0), r.get("gets_ejec") or "n/d", r.get("gets_fila") or "n/d",
                   int(r.get("planes") or 0), r.get("esquema") or "", " ".join(str(r.get("sql_text") or "").split()), "----"])
    for col, w in zip("ABCDEFGHIJKLM", (5, 16, 11, 11, 9, 12, 8, 14, 14, 8, 12, 70, 40)):
        ws.column_dimensions[col].width = w

    ws2 = wb.create_sheet("Evolución CPU diaria")
    ws2["A1"] = f"Evolución de CPU por día (segundos) — semana {label_a.replace(' ', '')}-{label_b.replace(' ', '')}"
    ws2["A2"] = "Fila concentrada en pocos días = proceso puntual; uniforme = carga sostenida."
    days = [monday + dt.timedelta(days=n) for n in range(5)]
    ws2.append([])
    ws2.append(["SQL_ID"] + [f"{WEEKDAYS[d.weekday()]} {d.day}" for d in days] + ["Total (h)"])
    by = {(r["sql_id"], str(r["dia"])): float(r.get("cpu_s") or 0) for r in daily}
    for r in top:
        vals = [by.get((r["sql_id"], d.isoformat()), 0) for d in days]
        ws2.append([r["sql_id"]] + vals + [round(sum(vals) / 3600, 1)])
    for c in ws2[4]:
        c.font = Font(bold=True)
    return wb


def generate_weekly(monday: dt.date, *, force: bool = False, fetch=None) -> dict[str, Any]:
    """Genera el Excel de la semana. Devuelve {file, status, rows}; status: ok | exists."""
    if fetch is None:
        from db import queries
        fetch = (queries.get_weekly_top_sql, queries.get_weekly_daily_cpu)
    top_fn, daily_fn = fetch
    folder = output_dir()
    target = folder / week_filename(monday)
    if target.exists() and not force:
        return {"file": target.name, "status": "exists", "rows": 0}
    d1, d2 = monday.isoformat(), (monday + dt.timedelta(days=5)).isoformat()
    top = [{k.lower(): v for k, v in r.items()} for r in top_fn(d1, d2, 33)]
    if not top:
        raise RuntimeError("DBA_HIST no devolvió SQL para esa semana.")
    daily = [{k.lower(): v for k, v in r.items()} for r in daily_fn(d1, d2, [r["sql_id"] for r in top])]
    folder.mkdir(parents=True, exist_ok=True)
    target = _unique(target)
    wb = build_workbook(monday, top, daily)
    tmp = target.with_name(f".{target.name}.tmp")
    wb.save(tmp)
    tmp.replace(target)
    return {"file": target.name, "status": "ok", "rows": len(top)}


# ---------- Estado y cron ----------
def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE_FILE)


def last_due(now: dt.datetime, day: int, hour: int) -> dt.date:
    """Lunes de la semana cuyo momento programado (día/hora) fue el último ya vencido."""
    monday = now.date() - dt.timedelta(days=now.weekday())
    moment = dt.datetime.combine(monday + dt.timedelta(days=day), dt.time(hour))
    return monday if now >= moment else monday - dt.timedelta(days=7)


def next_run(now: dt.datetime, day: int, hour: int) -> dt.datetime:
    monday = now.date() - dt.timedelta(days=now.weekday())
    moment = dt.datetime.combine(monday + dt.timedelta(days=day), dt.time(hour))
    return moment if moment > now else moment + dt.timedelta(days=7)


def run_weekly(monday: dt.date, *, force: bool = False, trigger: str = "auto", fetch=None) -> dict[str, Any]:
    with _lock:
        state = load_state()
        try:
            res = generate_weekly(monday, force=force, fetch=fetch)
            state.update(week=monday.isoformat(), file=res["file"], status=res["status"], rows=res["rows"], error=None)
        except Exception as exc:
            logger.exception("Fallo generando el informe semanal")
            state.update(week=monday.isoformat(), status="error", error=str(exc)[:300])
        state.update(run_at=dt.datetime.now().isoformat(timespec="seconds"), trigger=trigger)
        save_state(state)
        return state


def run_if_due(now: dt.datetime | None = None, fetch=None) -> bool:
    cfg = settings()
    now = now or dt.datetime.now()
    monday = last_due(now, cfg["weekly_day"], cfg["weekly_hour"])
    state = load_state()
    if state.get("week") == monday.isoformat() and state.get("status") in ("ok", "exists"):
        return False
    # Tras un error se reintenta como mucho cada hora.
    if state.get("week") == monday.isoformat() and state.get("status") == "error":
        try:
            if now - dt.datetime.fromisoformat(state["run_at"]) < dt.timedelta(hours=1):
                return False
        except (KeyError, ValueError):
            pass
    run_weekly(monday, trigger="auto", fetch=fetch)
    return True


async def weekly_loop() -> None:
    if not settings()["weekly_enabled"]:
        logger.info("Informe semanal automático desactivado (SIMBA_WEEKLY_ENABLED=false).")
        return
    while True:
        try:
            await asyncio.to_thread(run_if_due)
        except Exception:
            logger.exception("Fallo en el cron del informe semanal")
        await asyncio.sleep(600)


def list_reports() -> list[dict[str, Any]]:
    folder = output_dir()
    if not folder.is_dir():
        return []
    files = [p for p in folder.glob("PRAGU4E_Informe_Semana_*.xlsx") if not p.name.startswith(("~$", "."))]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": p.name, "size": p.stat().st_size,
             "modified": dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")} for p in files[:12]]


def report_path(name: str) -> Path | None:
    p = output_dir() / name
    if p.name != name or not name.startswith("PRAGU4E_Informe_Semana_") or not name.endswith(".xlsx") or not p.is_file():
        return None
    return p
