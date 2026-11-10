"""
query_reports/advisor.py
Recomendaciones sobre el informe semanal de queries de PRAGU4E (proyecto «proyecto_queries»).

Lee en solo lectura:
  - los Excel semanales «PRAGU4E_Informe_Semana_*.xlsx» (hoja «Listado Semanal …») de SIMBA_QUERY_REPORTS_DIR;
  - el Excel de seguimiento (hoja «Seguimiento») de SIMBA_QUERY_TRACKING_FILE, opcional.

Cruza la última semana con el seguimiento y aplica reglas de DBA, sin LLM. Los textos de las sugerencias
están en recommendations.json para que el DBA los ajuste sin tocar código. Nunca modifica los Excel.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger("query_reports.advisor")

RECOMMENDATIONS_FILE = Path(__file__).with_name("recommendations.json")
FUNCTIONAL_NOTE = "Las recomendaciones son sugerencias: antes de actuar, deben verificarlas el DBA y el equipo funcional."

GETS_PER_ROW_HIGH = 10_000
EXECS_HIGH, GETS_PER_EXEC_LOW = 100_000, 50_000
EXECS_BATCH, GETS_PER_EXEC_BATCH = 100, 10_000_000
STALLED_WEEKS = 4
# Una completada que sigue en el top se considera «sin efecto» si su CPU no ha bajado al menos este porcentaje.
REAPPEAR_MIN_DROP = 0.30

_MONTHS = {"ene": 1, "jan": 1, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8,
           "aug": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12, "dec": 12}
_SQL_ID = re.compile(r"[0-9a-z]{13}")
_PLSQL = re.compile(r"^\s*(call|begin|declare)\b", re.I)


def _reports_dir() -> Path | None:
    value = os.getenv("SIMBA_QUERY_REPORTS_DIR", "").strip()
    return Path(value).expanduser() if value else None


def _tracking_file() -> Path | None:
    value = os.getenv("SIMBA_QUERY_TRACKING_FILE", "").strip()
    return Path(value).expanduser() if value else None


def _num(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _fmt(value: float | None, decimals: int = 0) -> str:
    if value is None:
        return "n/d"
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _week_start(title: str, a1: str) -> tuple[dt.date | None, str | None]:
    """Lunes y etiqueta de la semana a partir de A1 o del nombre de la hoja («Lun 12 Oct – Vie 16 Oct 2026», «07-11 sept»)."""
    for text in (a1, title):
        m = re.search(r"(\d{1,2})\s*([A-Za-zé]{3})[A-Za-zé]*\.?\s*[–-]\s*(?:[A-Za-zé]+\.?\s+)?(\d{1,2})\s*"
                      r"([A-Za-zé]{3})[A-Za-zé]*\.?\s*(\d{4})?", text, re.I)
        if m and _MONTHS.get(m.group(2).lower()) and _MONTHS.get(m.group(4).lower()):
            d1, m1, d2, m2 = int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3)), _MONTHS[m.group(4).lower()]
            year = int(m.group(5)) if m.group(5) else dt.date.today().year
            start = dt.date(year if m1 <= m2 else year - 1, m1, d1)
            return start, f"{start:%d/%m}–{d2:02d}/{m2:02d}/{year}"
        m = re.search(r"(\d{1,2})\s*[–-]\s*(?:[A-Za-zé]+\.?\s+)?(\d{1,2})\s+([A-Za-zé]{3})[A-Za-zé]*\.?\s*(\d{4})?",
                      text, re.I)
        if m and _MONTHS.get(m.group(3).lower()):
            d1, d2, month = int(m.group(1)), int(m.group(2)), _MONTHS[m.group(3).lower()]
            year = int(m.group(4)) if m.group(4) else dt.date.today().year
            start = dt.date(year, month, d1) if d1 <= d2 else dt.date(year if month > 1 else year - 1, month - 1 or 12, d1)
            return start, f"{start:%d/%m}–{d2:02d}/{month:02d}/{year}"
    return None, None


def _header(rows: list[tuple], required: list[str]) -> tuple[int | None, dict[str, int]]:
    for i, row in enumerate(rows[:15]):
        cols = {" ".join(str(c).split()).upper(): j for j, c in enumerate(row) if c is not None}
        if all(any(k.startswith(r) for k in cols) for r in required):
            return i, cols
    return None, {}


def _col(cols: dict[str, int], prefix: str) -> int | None:
    return next((v for k, v in cols.items() if k.startswith(prefix)), None)


def _load_workbook(path: Path):
    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(path, read_only=True, data_only=True)


def read_weekly_reports(folder: Path) -> list[dict[str, Any]]:
    """Semanas encontradas en la carpeta, ordenadas de más antigua a más reciente."""
    weeks: dict[dt.date, dict[str, Any]] = {}
    for path in sorted(folder.glob("*.xlsx"), key=lambda p: p.stat().st_mtime):
        if path.name.startswith("~$"):
            continue
        wb = _load_workbook(path)
        try:
            for ws in wb.worksheets:
                if not ws.title.lower().startswith("listado semanal"):
                    continue
                rows = list(ws.iter_rows(values_only=True))
                start, label = _week_start(ws.title, str(rows[0][0] if rows and rows[0] else ""))
                head, cols = _header(rows, ["SQL_ID", "CPU TOTAL"])
                if head is None or start is None:
                    logger.warning("query_report_sheet_ignored file=%s sheet=%s", path.name, ws.title)
                    continue
                idx = {k: _col(cols, p) for k, p in [
                    ("sid", "SQL_ID"), ("prio", "PRIORIDAD"), ("cpu", "CPU TOTAL"), ("pct", "% CPU"),
                    ("ejec", "EJEC"), ("dias", "DÍAS"), ("gets", "GETS/EJEC"), ("gets_fila", "GETS POR FILA"),
                    ("planes", "PLANES"), ("esq", "ESQUEMA"), ("sql", "SQL_TEXT"), ("notas", "NOTAS")]}
                entries = {}
                for row in rows[head + 1:]:
                    value = lambda k: row[idx[k]] if idx[k] is not None and idx[k] < len(row) else None
                    sid = str(value("sid") or "").strip()
                    if not _SQL_ID.fullmatch(sid):
                        continue
                    entries[sid] = {
                        "prioridad": str(value("prio") or "").strip().upper(),
                        "cpu_h": _num(value("cpu")), "pct_cpu": _num(value("pct")),
                        "ejecuciones": _num(value("ejec")), "dias": _num(value("dias")),
                        "gets_ejec": _num(value("gets")), "gets_fila": _num(value("gets_fila")),
                        "planes": _num(value("planes")),
                        "esquema": str(value("esq") or "").strip(),
                        "sql_text": " ".join(str(value("sql") or "").split())[:300],
                        "notas": str(value("notas") or "").strip(),
                    }
                weeks[start] = {"monday": start, "label": label, "file": path.name, "rows": entries}
        finally:
            wb.close()
    return [weeks[k] for k in sorted(weeks)]


def read_tracking(path: Path) -> dict[str, dict[str, Any]]:
    """Filas de la hoja «Seguimiento» por SQL_ID."""
    wb = _load_workbook(path)
    try:
        rows = list(wb["Seguimiento"].iter_rows(values_only=True))
    finally:
        wb.close()
    head, cols = _header(rows, ["SQL_ID", "ESTADO"])
    if head is None:
        return {}
    names = {v: k for k, v in cols.items()}
    result = {}
    for row in rows[head + 1:]:
        record = {names[i]: row[i] for i in names if i < len(row)}
        sid = str(record.get("SQL_ID") or "").strip()
        if _SQL_ID.fullmatch(sid):
            result[sid] = record
    return result


@lru_cache(maxsize=1)
def _recommendations() -> dict[str, dict]:
    try:
        return json.loads(RECOMMENDATIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("query_recommendations_unavailable error=%s", type(exc).__name__)
        return {}


def _finding(kind: str, message: str) -> dict[str, str]:
    r = _recommendations().get(kind, {})
    return {"tipo": kind, "mensaje": message, "accion": r.get("accion", ""),
            "urgencia": r.get("urgencia", ""), "responsable": r.get("responsable", "")}


def _technical_findings(row: dict[str, Any]) -> list[dict[str, str]]:
    found = []
    planes, gets_fila, gets_ejec, ejec = row["planes"], row["gets_fila"], row["gets_ejec"], row["ejecuciones"]
    if planes and planes > 1:
        found.append(_finding("planes_multiples", f"{_fmt(planes)} planes de ejecución distintos en la semana."))
    if _PLSQL.match(row["sql_text"]) or ":ret :=" in row["sql_text"].lower():
        found.append(_finding("plsql", "Es una llamada PL/SQL: las lecturas incluyen todo lo que ejecuta dentro."))
        return found
    if gets_fila and gets_fila >= GETS_PER_ROW_HIGH:
        found.append(_finding("lecturas_por_fila", f"{_fmt(gets_fila)} bloques leídos por cada fila devuelta."))
    if ejec and gets_ejec is not None and ejec >= EXECS_HIGH and gets_ejec < GETS_PER_EXEC_LOW:
        found.append(_finding("muchas_ejecuciones",
                              f"{_fmt(ejec)} ejecuciones en la semana con {_fmt(gets_ejec)} lecturas cada una."))
    if ejec is not None and gets_ejec and ejec <= EXECS_BATCH and gets_ejec >= GETS_PER_EXEC_BATCH:
        found.append(_finding("batch_pesado", f"{_fmt(ejec)} ejecuciones de {_fmt(gets_ejec)} lecturas cada una."))
    return found


def _to_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(str(value or "").strip(), fmt).date()
        except ValueError:
            pass
    return None


def _date_text(value: Any) -> str:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.strftime("%d/%m/%Y")
    return str(value or "").strip()


def build_recommendations(weeks: list[dict[str, Any]], tracking: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Cruza la última semana con el seguimiento. Función pura: fácil de probar sin ficheros."""
    if not weeks:
        return {"week": None, "items": [], "kpis": {}, "note": FUNCTIONAL_NOTE}
    last = weeks[-1]
    previous = weeks[-2]["rows"] if len(weeks) > 1 else {}
    items = []
    for sid, row in last["rows"].items():
        t = tracking.get(sid)
        status = str(t.get("ESTADO") or "").strip() if t else "Sin seguimiento"
        weeks_top = int(_num(t.get("SEMANAS EN TOP")) or 0) if t else sum(1 for w in weeks if sid in w["rows"])
        findings = []
        if t is None and tracking:
            findings.append(_finding("nueva_sin_seguimiento",
                                     f"En el top con {_fmt(row['cpu_h'], 1)} h de CPU ({_fmt(row['pct_cpu'], 1)} % "
                                     f"de la semana), prioridad {row['prioridad'] or 'n/d'}, sin fila en el seguimiento."))
        elif status == "Completado":
            before = _num(t.get("CPU H/SEM (MEDIA)"))
            done = _to_date(t.get("FECHA COMPLETADO"))
            # Si se completó dentro de la semana del informe, aún no hay una semana completa para juzgarla.
            judged = done is None or done < last["monday"]
            if judged and row["cpu_h"] is not None and before and row["cpu_h"] >= before * (1 - REAPPEAR_MIN_DROP):
                findings.append(_finding("completada_reaparece",
                                         f"Completada el {_date_text(t.get('FECHA COMPLETADO')) or 'n/d'} y sigue en el "
                                         f"top: {_fmt(row['cpu_h'], 1)} h esta semana frente a {_fmt(before, 1)} h/sem "
                                         f"de media."))
        elif t is not None and weeks_top >= STALLED_WEEKS:
            findings.append(_finding("estancada",
                                     f"{weeks_top} semanas en el top en estado «{status}»"
                                     f" (responsable: {t.get('PERSONA') or 'sin asignar'})."))
        if status != "Completado" or findings:
            findings.extend(_technical_findings(row))
        if not findings:
            continue
        if t and t.get("PERSONA"):
            for f in findings:
                f["responsable"] = f["responsable"].replace("Responsable asignado", str(t["PERSONA"]))
        prev_cpu = previous.get(sid, {}).get("cpu_h")
        items.append({
            "sql_id": sid, "esquema": row["esquema"] or (t or {}).get("ESQUEMA"),
            "prioridad": row["prioridad"], "estado": status, "persona": (t or {}).get("PERSONA"),
            "cpu_h": row["cpu_h"], "pct_cpu": row["pct_cpu"], "cpu_h_semana_anterior": prev_cpu,
            "ejecuciones": row["ejecuciones"], "gets_ejec": row["gets_ejec"], "gets_fila": row["gets_fila"],
            "planes": row["planes"], "semanas_top": weeks_top, "sql_text": row["sql_text"],
            "notas": row["notas"], "hallazgos": findings,
        })

    for sid, t in tracking.items():
        if str(t.get("ESTADO") or "").strip() != "Completado" or sid in last["rows"]:
            continue
        check = str(t.get("COMPROBACIÓN") or "")
        kind = "completada_empeora" if "Empeora" in check else "completada_sin_medir" if "Faltan tiempos" in check else ""
        if kind:
            message = ("El tiempo después del cambio es mayor que el de antes." if kind == "completada_empeora"
                       else "Ha salido del top, pero no tiene tiempos antes/después medidos.")
            items.append({"sql_id": sid, "esquema": t.get("ESQUEMA"), "prioridad": t.get("PRIORIDAD"),
                          "estado": "Completado", "persona": t.get("PERSONA"), "cpu_h": None, "pct_cpu": None,
                          "semanas_top": int(_num(t.get("SEMANAS EN TOP")) or 0),
                          "sql_text": " ".join(str(t.get("SQL_TEXT") or "").split())[:300],
                          "hallazgos": [_finding(kind, message)]})

    items.sort(key=lambda i: (i["cpu_h"] is None, -(i["cpu_h"] or 0)))
    total_cpu = sum(r["cpu_h"] or 0 for r in last["rows"].values())
    untracked = [s for s in last["rows"] if s not in tracking] if tracking else []
    kinds = [f["tipo"] for i in items for f in i["hallazgos"]]
    completed_out = [s for s, t in tracking.items()
                     if str(t.get("ESTADO") or "").strip() == "Completado" and s not in last["rows"]]
    return {
        "week": last["label"], "file": last["file"], "weeks_available": len(weeks),
        "kpis": {
            "sql_en_top": len(last["rows"]),
            "cpu_total_top_h": round(total_cpu, 1),
            "sin_seguimiento": len(untracked),
            "cpu_sin_seguimiento_h": round(sum(last["rows"][s]["cpu_h"] or 0 for s in untracked), 1),
            "completadas_que_reaparecen": kinds.count("completada_reaparece"),
            "completadas_fuera_del_top": len(completed_out),
            "estancadas": kinds.count("estancada"),
            "seguimiento_configurado": bool(tracking),
        },
        "items": items,
        "note": FUNCTIONAL_NOTE,
    }


@lru_cache(maxsize=4)
def _cached(folder: str, tracking: str, stamp: tuple) -> dict[str, Any]:
    weeks = read_weekly_reports(Path(folder))
    track = read_tracking(Path(tracking)) if tracking else {}
    return build_recommendations(weeks, track)


def get_query_improvements() -> dict[str, Any]:
    """Resultado listo para la web y el agente; se recalcula solo si cambian los ficheros."""
    folder, tracking = _reports_dir(), _tracking_file()
    if not folder:
        return {"configured": False, "error": "Falta SIMBA_QUERY_REPORTS_DIR (carpeta de los informes semanales)."}
    if not folder.is_dir():
        return {"configured": False, "error": f"No existe la carpeta de informes: {folder}"}
    if tracking and not tracking.is_file():
        logger.warning("query_tracking_missing path=%s", tracking)
        tracking = None
    stamp = tuple(sorted((p.name, p.stat().st_mtime) for p in folder.glob("*.xlsx")))
    if tracking:
        stamp += ((tracking.name, tracking.stat().st_mtime),)
    try:
        result = dict(_cached(str(folder), str(tracking or ""), stamp))
    except Exception as exc:
        logger.exception("query_reports_failed")
        return {"configured": True, "error": f"No se pudieron leer los informes ({type(exc).__name__})."}
    result["configured"] = True
    return result


def format_query_improvements(result: dict[str, Any], sql_id: str | None = None, limit: int = 10) -> str:
    """Texto para el asistente."""
    if result.get("error"):
        return f"No hay recomendaciones de queries: {result['error']}"
    if not result.get("week"):
        return "No se ha encontrado ningún informe semanal en la carpeta configurada."
    items = result["items"]
    if sql_id:
        items = [i for i in items if i["sql_id"] == sql_id.strip().lower()]
        if not items:
            return f"{sql_id} no tiene recomendaciones en la semana {result['week']} (o no está en el top)."
    k = result["kpis"]
    lines = [f"Informe semanal {result['week']} ({result['file']}): {k['sql_en_top']} SQL en el top, "
             f"{_fmt(k['cpu_total_top_h'], 1)} h de CPU."]
    if k["seguimiento_configurado"]:
        lines.append(f"Sin seguimiento: {k['sin_seguimiento']} ({_fmt(k['cpu_sin_seguimiento_h'], 1)} h). "
                     f"Completadas que reaparecen: {k['completadas_que_reaparecen']}. Estancadas: {k['estancadas']}. "
                     f"Completadas fuera del top: {k['completadas_fuera_del_top']}.")
    for i in items[:limit]:
        head = (f"- {i['sql_id']} ({i['esquema'] or 'n/d'}, {i['prioridad'] or 'n/d'}, estado {i['estado']}"
                + (f", {i['persona']}" if i.get("persona") else "")
                + (f", {_fmt(i['cpu_h'], 1)} h CPU" if i.get("cpu_h") is not None else "") + ")")
        lines.append(head)
        for f in i["hallazgos"]:
            lines.append(f"    · {f['mensaje']} Sugerencia: {f['accion']} (responsable: {f['responsable']})")
    if len(items) > limit:
        lines.append(f"... y {len(items) - limit} SQL más con recomendaciones.")
    lines.append(result["note"])
    return "\n".join(lines)
