"""
Análisis de una SQL problemática (solo DBA en la web). Solo SELECT sobre GV$/AWR/diccionario y reglas
deterministas, sin IA: el asistente puede explicar el resultado si se le pide.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import threading
import time
from typing import Any, Callable

from query_reports.advisor import FUNCTIONAL_NOTE, _finding, _fmt

logger = logging.getLogger("query_reports.sql_analysis")

SQL_ID_RE = re.compile(r"^[0-9a-z]{13}$")
CACHE_SECONDS = 300
HISTORY_DAYS = 30
TREND_DAYS = 14
UNSTABLE_RATIO = 3.0
UNSTABLE_MIN_EXECS = 5
WORSE_RATIO = 1.5
WORSE_MIN_EXECS = 10
STATS_OLD_DAYS = 90
STATS_CHANGED_PCT = 0.05
FULL_SCAN_MIN_ROWS = 1_000_000
MANY_CHILDREN = 20
GETS_PER_ROW_HIGH = 10_000

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()


def _as_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    return value if isinstance(value, dt.date) else None


def _weighted_elapsed(rows: list[dict]) -> tuple[float | None, float]:
    execs = sum(r.get("EJECUCIONES") or 0 for r in rows)
    if not execs:
        return None, 0
    total = sum((r.get("ELAPSED_S_EJEC") or 0) * (r.get("EJECUCIONES") or 0) for r in rows)
    return total / execs, execs


def main_plan_hash(cursors: list[dict], history: list[dict]) -> int | None:
    """Plan del cursor activo más reciente; si no hay en memoria, el que más CPU consumió en el AWR."""
    for c in cursors:
        if c.get("PLAN_HASH_VALUE"):
            return c["PLAN_HASH_VALUE"]
    for h in history:
        if h.get("PLAN_HASH_VALUE"):
            return h["PLAN_HASH_VALUE"]
    return None


def evaluate(data: dict[str, Any], context: dict[str, Any] | None = None,
             today: dt.date | None = None) -> list[dict[str, str]]:
    """Reglas sobre los datos recogidos. Función pura para poder probarla sin Oracle."""
    today = today or dt.date.today()
    cursors, history, trend = data.get("cursores", []), data.get("planes", []), data.get("tendencia", [])
    tables, indexes, plan = data.get("tablas", []), data.get("indices", []), data.get("plan", {}).get("lineas", [])
    children = data.get("plsql_hijas", [])
    found = []

    if not cursors and not history:
        return [_finding("analisis_sin_datos", "Sin cursores en memoria ni histórico en el AWR.")]

    usable = [h for h in history if (h.get("EJECUCIONES") or 0) >= UNSTABLE_MIN_EXECS and h.get("ELAPSED_S_EJEC")]
    if len(usable) >= 2:
        best = min(usable, key=lambda h: h["ELAPSED_S_EJEC"])
        worst = max(usable, key=lambda h: h["ELAPSED_S_EJEC"])
        if worst["ELAPSED_S_EJEC"] >= best["ELAPSED_S_EJEC"] * UNSTABLE_RATIO:
            found.append(_finding("analisis_plan_inestable",
                                  f"{len(history)}{' o más' if len(history) >= 20 else ''} planes en {HISTORY_DAYS} días. El mejor ({best['PLAN_HASH_VALUE']}) "
                                  f"tarda {_fmt(best['ELAPSED_S_EJEC'], 2)} s por ejecución y el peor "
                                  f"({worst['PLAN_HASH_VALUE']}) {_fmt(worst['ELAPSED_S_EJEC'], 2)} s."))

    if trend:
        last_day = max(_as_date(r["DIA"]) for r in trend if _as_date(r.get("DIA")))
        recent = [r for r in trend if _as_date(r.get("DIA")) and (last_day - _as_date(r["DIA"])).days < 7]
        before = [r for r in trend if _as_date(r.get("DIA")) and (last_day - _as_date(r["DIA"])).days >= 7]
        now, now_ex = _weighted_elapsed(recent)
        prev, prev_ex = _weighted_elapsed(before)
        if now and prev and now_ex >= WORSE_MIN_EXECS and prev_ex >= WORSE_MIN_EXECS and now >= prev * WORSE_RATIO:
            found.append(_finding("analisis_empeora",
                                  f"Últimos 7 días: {_fmt(now, 2)} s por ejecución frente a {_fmt(prev, 2)} s "
                                  f"la semana anterior (+{_fmt((now / prev - 1) * 100)} %)."))

    stale = []
    for t in tables:
        analyzed, rows, changes = _as_date(t.get("ULTIMO_ANALISIS")), t.get("FILAS") or 0, t.get("MODIFICACIONES") or 0
        old = analyzed is not None and (today - analyzed).days > STATS_OLD_DAYS and changes >= rows * STATS_CHANGED_PCT
        if t.get("OBSOLETAS") == "YES" or analyzed is None or old:
            reason = ("sin estadísticas" if analyzed is None else "marcadas obsoletas" if t.get("OBSOLETAS") == "YES"
                      else f"de hace {(today - analyzed).days} días con {_fmt(changes)} cambios")
            locked = " (bloqueadas)" if t.get("BLOQUEADAS") else ""
            stale.append(f"{t['PROPIETARIO']}.{t['TABLA']} {reason}{locked}")
    if stale:
        found.append(_finding("analisis_estadisticas", "Estadísticas: " + "; ".join(stale[:6]) + "."))

    sizes = {(t["PROPIETARIO"], t["TABLA"]): t.get("FILAS") or 0 for t in tables}
    full = sorted({f"{p['PROPIETARIO']}.{p['OBJETO']} ({_fmt(sizes[(p['PROPIETARIO'], p['OBJETO'])])} filas)"
                   for p in plan if p.get("OPERACION") == "TABLE ACCESS" and "FULL" in (p.get("OPCIONES") or "")
                   and sizes.get((p.get("PROPIETARIO"), p.get("OBJETO")), 0) >= FULL_SCAN_MIN_ROWS})
    if full:
        found.append(_finding("analisis_full_scan", "Lectura completa de: " + ", ".join(full[:5]) + "."))

    if any("CARTESIAN" in (p.get("OPCIONES") or "") for p in plan):
        found.append(_finding("analisis_cartesiano", "El plan principal contiene MERGE JOIN CARTESIAN."))

    bad = [f"{i['INDICE']} ({i['ESTADO'] if i.get('ESTADO') == 'UNUSABLE' else i.get('VISIBILIDAD')})"
           for i in indexes if i.get("ESTADO") == "UNUSABLE" or i.get("VISIBILIDAD") == "INVISIBLE"]
    if bad:
        found.append(_finding("analisis_indice_no_usable", "Índices: " + ", ".join(bad[:6]) + "."))

    if len(cursors) >= MANY_CHILDREN:
        top = "50 o más" if len(cursors) >= 50 else str(len(cursors))
        found.append(_finding("analisis_muchos_hijos", f"{top} cursores hijos en memoria."))

    main = data.get("plan", {}).get("plan_hash_value")
    stats = next((h for h in history if h.get("PLAN_HASH_VALUE") == main), history[0] if history else None)
    if stats and stats.get("LECTURAS_EJEC") and main:
        per_row = stats["LECTURAS_EJEC"] / max(stats.get("FILAS_EJEC") or 0, 1)
        if per_row >= GETS_PER_ROW_HIGH:
            found.append(_finding("analisis_lecturas_por_fila",
                                  f"{_fmt(stats['LECTURAS_EJEC'])} lecturas por ejecución para "
                                  f"{_fmt(stats.get('FILAS_EJEC') or 0, 1)} filas (≈{_fmt(per_row)} por fila)."))

    if children:
        top = ", ".join(f"{c['SQL_ID']} ({c['MUESTRAS']} muestras)" for c in children[:3])
        found.append(_finding("analisis_plsql_hijas", f"SQL hijas con más tiempo en las últimas horas: {top}."))

    hints = " ".join(str((context or {}).get(k) or "") for k in ("notas", "query_mejora", "notas_analisis")).lower()
    if "baseline" in hints and cursors and not any(c.get("SQL_PLAN_BASELINE") for c in cursors):
        found.append(_finding("analisis_baseline_no_aplicada",
                              "El seguimiento menciona una baseline, pero ningún cursor en memoria la usa."))
    return found


def _collect(sql_id: str) -> dict[str, Any]:
    from db import queries as q

    data: dict[str, Any] = {"errores": {}}

    def run(key: str, fn: Callable[[], Any], default: Any) -> None:
        try:
            data[key] = fn()
        except Exception as exc:  # una vista sin permiso o lenta no debe tumbar el resto del análisis
            logger.warning("sql_analysis_section_failed section=%s error=%s", key, type(exc).__name__)
            data[key] = default
            data["errores"][key] = str(exc).split("\n")[0][:160]

    run("cursores", lambda: q.get_sql_cursors(sql_id), [])
    run("planes", lambda: q.get_sql_plan_history(sql_id, HISTORY_DAYS), [])
    run("tendencia", lambda: q.get_sql_daily_trend(sql_id, TREND_DAYS), [])
    phv = main_plan_hash(data["cursores"], data["planes"])
    run("plan", lambda: {"plan_hash_value": phv,
                         "lineas": q.get_sql_plan_lines(sql_id, phv) if phv else []}, {"plan_hash_value": phv, "lineas": []})
    run("tablas", lambda: q.get_sql_table_stats(sql_id), [])
    run("indices", lambda: q.get_sql_table_indexes(sql_id), [])
    run("plsql_hijas", lambda: q.get_plsql_child_sqls(sql_id) if not phv else [], [])
    return data


def _summary(sql_id: str, data: dict[str, Any]) -> dict[str, Any]:
    cursors = data["cursores"]
    first = cursors[0] if cursors else {}
    return {
        "esquema": first.get("ESQUEMA"),
        "modulo": first.get("MODULO"),
        "cursores_en_memoria": len(cursors),
        "planes_en_memoria": len({c.get("PLAN_HASH_VALUE") for c in cursors}),
        "planes_awr": len(data["planes"]),
        "plan_principal": data["plan"].get("plan_hash_value"),
        "origen_plan": (data["plan"]["lineas"][0]["ORIGEN"] if data["plan"].get("lineas") else None),
        "baselines": sorted({c["SQL_PLAN_BASELINE"] for c in cursors if c.get("SQL_PLAN_BASELINE")}),
        "perfiles": sorted({c["SQL_PROFILE"] for c in cursors if c.get("SQL_PROFILE")}),
        "sql_texto": first.get("SQL_TEXTO"),
    }


def analyze_sql(sql_id: str, context: dict[str, Any] | None = None, force: bool = False) -> dict[str, Any]:
    """Análisis completo de una SQL_ID (con caché de unos minutos para no repetir consultas)."""
    sql_id = (sql_id or "").strip().lower()
    if not SQL_ID_RE.fullmatch(sql_id):
        raise ValueError("SQL_ID no válido: deben ser 13 caracteres alfanuméricos en minúscula.")
    with _lock:
        hit = _cache.get(sql_id)
    if hit and not force and time.time() - hit[0] < CACHE_SECONDS:
        data = hit[1]
    else:
        data = _collect(sql_id)
        data["generado"] = dt.datetime.now().isoformat(timespec="seconds")
        with _lock:
            _cache[sql_id] = (time.time(), data)
    return {
        "sql_id": sql_id,
        "generado": data["generado"],
        "resumen": _summary(sql_id, data),
        "hallazgos": evaluate(data, context),
        "planes": data["planes"],
        "tendencia": data["tendencia"],
        "plan": data["plan"],
        "tablas": data["tablas"],
        "indices": data["indices"],
        "cursores": data["cursores"][:20],
        "plsql_hijas": data["plsql_hijas"],
        "errores": data["errores"],
        "note": FUNCTIONAL_NOTE,
    }


def format_sql_analysis(result: dict[str, Any]) -> str:
    """Texto para el asistente."""
    r = result["resumen"]
    lines = [f"Análisis de la SQL {result['sql_id']} ({result['generado']}): esquema {r['esquema'] or 'n/d'}, "
             f"{r['cursores_en_memoria']} cursores en memoria, {r['planes_awr']} planes en el AWR "
             f"({HISTORY_DAYS} días), plan principal {r['plan_principal'] or 'n/d'}."]
    if r["baselines"] or r["perfiles"]:
        lines.append(f"Usa baseline: {', '.join(r['baselines']) or 'no'}; perfil: {', '.join(r['perfiles']) or 'no'}.")
    for h in result["planes"][:5]:
        lines.append(f"- Plan {h['PLAN_HASH_VALUE'] or '0 (sin plan: PL/SQL o ejecución en curso)'}: {_fmt(h.get('EJECUCIONES'))} ejec., "
                     f"{_fmt(h.get('ELAPSED_S_EJEC'), 2)} s/ejec., {_fmt(h.get('LECTURAS_EJEC'))} lecturas/ejec., "
                     f"{_fmt(h.get('CPU_H'), 1)} h CPU.")
    if result["hallazgos"]:
        lines.append("Hallazgos:")
        for f in result["hallazgos"]:
            lines.append(f"- {f['mensaje']} Sugerencia: {f['accion']} (responsable: {f['responsable']})")
    else:
        lines.append("No se detecta nada destacable con las reglas actuales.")
    if result["errores"]:
        lines.append("No se pudo consultar: " + ", ".join(result["errores"]) + ".")
    lines.append(result["note"])
    return "\n".join(lines)
