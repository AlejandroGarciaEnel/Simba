"""
health/checker.py
Revisión única del estado de la BBDD, sin LLM: ejecuta las consultas, aplica reglas
de un DBA y devuelve hallazgos con severidad y causa probable. El resultado se guarda
en el histórico y se reutiliza mientras no caduque (caché), para no repetir consultas
ni gastar tokens.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import db.queries as q
from health.store import HealthStore

logger = logging.getLogger("health.checker")

OK, INFO, WARNING, CRITICAL = "OK", "INFO", "WARNING", "CRITICAL"
_ORDER = {OK: 0, INFO: 1, WARNING: 2, CRITICAL: 3}

CPU_WARN, CPU_CRIT = 60.0, 85.0
LIMIT_WARN, LIMIT_CRIT = 80.0, 90.0
TABLESPACE_WARN, TABLESPACE_CRIT = 85.0, 95.0
BLOCK_WARN_SECONDS, BLOCK_CRIT_SECONDS = 30, 300
INACTIVE_WARN = 20
CRITICAL_ORA = ("ORA-00600", "ORA-07445", "ORA-04031", "ORA-01555", "ORA-00257")


def cache_ttl() -> timedelta:
    try:
        minutes = float(os.environ.get("SIMBA_HEALTH_CACHE_MINUTES", "10"))
    except ValueError:
        minutes = 10.0
    return timedelta(minutes=max(0.0, minutes))


FUNCTIONAL_NOTE = "Las recomendaciones son sugerencias: antes de actuar, debe verificarlas el equipo funcional."
RECOMMENDATIONS_FILE = Path(__file__).with_name("recommendations.json")


@lru_cache(maxsize=1)
def _recommendations() -> dict[str, dict[str, Any]]:
    """Recomendaciones redactadas por el DBA (health/recommendations.json). Si falta, no se rompe la revisión."""
    try:
        data = json.loads(RECOMMENDATIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("recommendations_unavailable error=%s", type(exc).__name__)
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def _finding(area: str, severity: str, message: str, rec: str = "") -> dict[str, str]:
    r = _recommendations().get(rec, {})
    return {"area": area, "severity": severity, "message": message,
            "action": r.get("accion", ""), "urgency": r.get("urgencia", ""),
            "owner": r.get("responsable", "")}


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _eval_cpu(data: float) -> list[dict]:
    if data >= CPU_CRIT:
        return [_finding("CPU", CRITICAL, f"CPU al {data:.1f}%.",
                         "cpu_alta")]
    if data >= CPU_WARN:
        return [_finding("CPU", WARNING, f"CPU al {data:.1f}%.", "cpu_alta")]
    return [_finding("CPU", OK, f"CPU al {data:.1f}%.")]


def _eval_blocking(rows: list[dict]) -> list[dict]:
    if not rows:
        return [_finding("Bloqueos", OK, "No hay sesiones bloqueadas.")]
    worst = max(rows, key=lambda r: _num(r.get("SEGUNDOS_ESPERA")))
    wait = int(_num(worst.get("SEGUNDOS_ESPERA")))
    blockers = {r.get("SID_BLOQUEANTE") for r in rows}
    severity = CRITICAL if wait >= BLOCK_CRIT_SECONDS else WARNING if wait >= BLOCK_WARN_SECONDS else INFO
    msg = (f"{len(rows)} sesión(es) bloqueada(s) por {len(blockers)} bloqueante(s). "
           f"La espera mayor es de {wait} s (SID {worst.get('SID_BLOQUEADA')} esperando a SID "
           f"{worst.get('SID_BLOQUEANTE')}, usuario {worst.get('USUARIO_BLOQUEANTE')}, "
           f"programa {worst.get('PROGRAMA_BLOQUEANTE')}, máquina {worst.get('MAQUINA_BLOQUEANTE')}).")
    rec = "bloqueo_corto"
    if worst.get("ESTADO_BLOQUEANTE") == "INACTIVE" and wait >= BLOCK_WARN_SECONDS:
        idle = int(_num(worst.get("SEGUNDOS_ULTIMA_LLAMADA")))
        msg += f" El bloqueante está INACTIVE desde hace {idle} s."
        rec = "bloqueo_transaccion_abierta"
    elif wait >= BLOCK_WARN_SECONDS:
        rec = "bloqueo_en_ejecucion"
    return [_finding("Bloqueos", severity, msg, rec)]


def _eval_limits(rows: list[dict]) -> list[dict]:
    findings = []
    for r in rows:
        name, limit = r.get("RESOURCE_NAME"), str(r.get("LIMIT_VALUE") or "").strip()
        if not limit.isdigit() or int(limit) == 0:
            continue
        pct = _num(r.get("CURRENT_UTILIZATION")) * 100 / int(limit)
        sev = CRITICAL if pct >= LIMIT_CRIT else WARNING if pct >= LIMIT_WARN else OK
        rec = "conexiones_cerca_limite" if sev != OK else ""
        findings.append(_finding("Conexiones", sev,
                                 f"{name}: {int(_num(r.get('CURRENT_UTILIZATION')))} de {limit} ({pct:.0f}%).", rec))
    return findings or [_finding("Conexiones", INFO, "Sin límites numéricos que evaluar.")]


def _eval_tablespaces(rows: list[dict]) -> list[dict]:
    findings = []
    permanent: dict[str, list[str]] = {CRITICAL: [], WARNING: []}
    for r in rows:
        pct = _num(r.get("USED_PCT"))
        if pct < TABLESPACE_WARN:
            continue
        sev = CRITICAL if pct >= TABLESPACE_CRIT else WARNING
        kind = str(r.get("CONTENTS") or "")
        label = f"{r.get('TABLESPACE_NAME')} ({pct:.1f}%)"
        if kind in ("TEMPORARY", "UNDO"):
            findings.append(_finding("TEMP" if kind == "TEMPORARY" else "UNDO", sev, f"Tablespace {label}.",
                                     "espacio_temp" if kind == "TEMPORARY" else "espacio_undo"))
        else:
            permanent[sev].append(label)
    for sev, names in permanent.items():
        if names:
            findings.append(_finding("Espacio", sev, f"{len(names)} tablespace(s) por encima del "
                                     f"{TABLESPACE_CRIT if sev == CRITICAL else TABLESPACE_WARN:.0f}%: "
                                     f"{', '.join(names)}.",
                                     "espacio_tablespace"))
    return findings or [_finding("Espacio", OK, f"Ningún tablespace supera el {TABLESPACE_WARN:.0f}%.")]


def _eval_inactive(total: int) -> list[dict]:
    if total >= INACTIVE_WARN:
        return [_finding("Sesiones", WARNING, f"{total} sesiones inactivas más de 30 min.",
                         "sesiones_inactivas")]
    return [_finding("Sesiones", OK, f"{total} sesiones inactivas más de 30 min.")]


def _eval_errors(rows: list[dict]) -> list[dict]:
    if not rows:
        return [_finding("Errores", OK, "Sin errores ORA- en la última hora del alert log.")]
    critical = [r for r in rows if any(c in str(r.get("MENSAJE")) for c in CRITICAL_ORA)]
    sev = CRITICAL if critical else WARNING
    rec = "errores_ora_graves" if critical else "errores_ora"
    last = rows[0]
    return [_finding("Errores", sev, f"{len(rows)} error(es) ORA- en la última hora. Último: "
                     f"[{last.get('FECHA')}] {last.get('MENSAJE')}",
                     rec)]


def _eval_waits(rows: list[dict]) -> list[dict]:
    if not rows:
        return [_finding("Esperas", OK, "No hay sesiones activas esperando en este momento.")]
    top = rows[0]
    return [_finding("Esperas", INFO, f"Espera dominante: {top.get('EVENTO')} ({top.get('CLASE')}) "
                     f"con {top.get('SESIONES')} sesión(es).")]


def _eval_longops(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    top = rows[0]
    return [_finding("Operaciones largas", INFO,
                     f"{len(rows)} operación(es) larga(s) en curso; la mayor: {top.get('OPERACION')} de "
                     f"{top.get('USUARIO')} al {top.get('PCT_COMPLETADO')}%.")]


# (clave, función de datos, evaluador)
_CHECKS: list[tuple[str, Callable[[], Any], Callable[[Any], list[dict]]]] = [
    ("cpu", lambda: q.get_cpu_usage(), _eval_cpu),
    ("bloqueos", lambda: q.get_blocked_waits(), _eval_blocking),
    ("limites", lambda: q.get_resource_limits(), _eval_limits),
    ("tablespaces", lambda: q.get_tablespace_usage(), _eval_tablespaces),
    ("sesiones_inactivas", lambda: q.get_cluster_inactive_sessions(), _eval_inactive),
    ("errores_ora", lambda: q.get_recent_ora_errors(), _eval_errors),
    ("esperas", lambda: q.get_current_wait_events(), _eval_waits),
    ("operaciones_largas", lambda: q.get_long_operations(), _eval_longops),
]


def _build_summary(overall: str, findings: list[dict]) -> str:
    problems = [f for f in findings if f["severity"] in (WARNING, CRITICAL)]
    if not problems:
        unavailable = [f["area"] for f in findings if f["severity"] == INFO and "No disponible" in f["message"]]
        text = ("La base de datos no muestra anomalías en las comprobaciones realizadas. Si las aplicaciones "
                "fallan, el problema está probablemente fuera de Oracle (red, aplicación, servidor web).")
        if unavailable:
            text += f" Comprobaciones no disponibles: {', '.join(unavailable)}."
        return text
    ordered = sorted(problems, key=lambda f: -_ORDER[f["severity"]])
    lines = [f"Estado global: {overall}."]
    for f in ordered:
        line = f"- [{f['severity']}] {f['area']}: {f['message']}"
        if f["action"]:
            line += f"\n    Recomendación: {f['action']}"
            extra = "; ".join(x for x in (f.get("urgency") and f"urgencia: {f['urgency']}",
                                          f.get("owner") and f"responsable: {f['owner']}") if x)
            if extra:
                line += f" ({extra})"
        lines.append(line)
    lines.append(FUNCTIONAL_NOTE)
    return "\n".join(lines)


def run_checks() -> dict[str, Any]:
    """Ejecuta todas las comprobaciones; una que falle (p. ej. por permisos) no aborta el resto."""
    findings: list[dict] = []
    raw: dict[str, Any] = {}
    for key, fetch, evaluate in _CHECKS:
        try:
            data = fetch()
        except Exception as exc:
            logger.warning("health_check_unavailable check=%s error=%s", key, type(exc).__name__)
            raw[key] = {"error": type(exc).__name__}
            findings.append(_finding(key, INFO, f"No disponible: {key} ({type(exc).__name__})."))
            continue
        raw[key] = data
        findings.extend(evaluate(data))
    overall = max((f["severity"] for f in findings), key=_ORDER.get, default=OK)
    return {"overall": overall, "findings": findings, "raw": raw, "summary": _build_summary(overall, findings)}


def get_health(requested_by: str = "anonimo", force_refresh: bool = False,
               store: HealthStore | None = None) -> dict[str, Any]:
    """Devuelve la última revisión si no ha caducado; si no (o si se fuerza), ejecuta una nueva."""
    store = store or HealthStore()
    latest = store.latest_check()
    if latest and not force_refresh:
        created = datetime.fromisoformat(latest["created_at"])
        if datetime.now(timezone.utc) - created < cache_ttl():
            store.log_request(requested_by, latest["id"], from_cache=True)
            return {**latest, "from_cache": True}

    result = run_checks()
    check_id = store.save_check(result["overall"], result["summary"], result["findings"], result["raw"])
    store.log_request(requested_by, check_id, from_cache=False)
    created_at = store.latest_check()["created_at"]
    return {"id": check_id, "created_at": created_at, "overall": result["overall"],
            "summary": result["summary"], "findings": result["findings"], "from_cache": False}


def format_health(result: dict[str, Any]) -> str:
    """Texto para el usuario: siempre indica la hora del dato y si viene de caché."""
    origin = "de caché" if result["from_cache"] else "recién ejecutada"
    head = f"Revisión {origin} (datos de {result['created_at']} UTC). Estado global: {result['overall']}."
    ok_areas = sorted({f["area"] for f in result["findings"] if f["severity"] == OK})
    tail = f"\nSin incidencias en: {', '.join(ok_areas)}." if ok_areas and result["overall"] != OK else ""
    return f"{head}\n{result['summary']}{tail}"
