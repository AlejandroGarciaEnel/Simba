"""
agent/tools.py
Herramientas LangChain (@tool). Una por cada RF.
Todas las herramientas aceptan un parámetro opcional 'limit' (por defecto 5).
"""
from __future__ import annotations

from tabulate import tabulate

from langchain_core.tools import tool

import db.queries as q


# ── RF001 ─────────────────────────────────────────────────────────────────────
@tool
def get_cpu_usage(_: str = "") -> str:
    """
    Devuelve el porcentaje de CPU que está utilizando la base de datos en este momento.
    No necesita ningún parámetro.
    """
    pct = q.get_cpu_usage()
    return f"CPU actual de la base de datos: {pct:.2f}%"


# ── RF002 ─────────────────────────────────────────────────────────────────────
@tool
def get_top_cpu_queries(limit: int = 5) -> str:
    """
    Devuelve las queries (SQLs) que más CPU están demandando en la base de datos.
    Parámetro opcional 'limit': número de resultados a devolver (por defecto 5).
    """
    rows = q.get_top_cpu_queries(limit)
    if not rows:
        return "No se encontraron queries con consumo de CPU significativo."
    headers = ["Usuario", "Ejecuciones", "% CPU", "CPU Time", "SQL"]
    table = [
        [r.get("USUARIO"), r.get("EJECUCIONES"), r.get("PCT_CPU"),
         r.get("CPU_TIME"), str(r.get("SQL") or "")[:120]]
        for r in rows
    ]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF003 ─────────────────────────────────────────────────────────────────────
@tool
def get_top_cpu_sessions(limit: int = 5) -> str:
    """
    Devuelve las sesiones activas que más CPU están demandando en la base de datos.
    Parámetro opcional 'limit': número de resultados a devolver (por defecto 5).
    """
    rows = q.get_top_cpu_sessions(limit)
    if not rows:
        return "No se encontraron sesiones activas con consumo de CPU significativo."
    headers = ["SID", "SERIAL#", "Usuario", "CPU (cs)", "% CPU"]
    table = [
        [r.get("SID"), r.get("SERIAL"), r.get("USUARIO"),
         r.get("CPU_CS"), r.get("PCT_CPU")]
        for r in rows
    ]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF004 ─────────────────────────────────────────────────────────────────────
@tool
def get_users_with_inactive_sessions(limit: int = 5) -> str:
    """
    Devuelve los usuarios con más sesiones inactivas (sin actividad > 30 minutos).
    Parámetro opcional 'limit': número de resultados a devolver (por defecto 5).
    """
    rows = q.get_users_with_inactive_sessions(limit)
    if not rows:
        return "No se encontraron usuarios con sesiones inactivas superiores a 30 minutos."
    headers = ["Usuario", "Sesiones Inactivas", "% CPU"]
    table = [
        [r.get("USUARIO"), r.get("SESIONES_INACTIVAS"), r.get("PCT_CPU")]
        for r in rows
    ]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF004.1 ───────────────────────────────────────────────────────────────────
@tool
def get_inactive_sessions(limit: int = 5) -> str:
    """
    Devuelve el detalle de las sesiones inactivas u huérfanas (sin actividad > 30 minutos).
    Parámetro opcional 'limit': número de resultados a devolver (por defecto 5).
    """
    rows = q.get_inactive_sessions(limit)
    if not rows:
        return "No se encontraron sesiones inactivas superiores a 30 minutos."
    headers = ["SID", "SERIAL#", "Usuario", "Idle (min)", "% CPU", "Mem (MB)", "Máquina", "Logon Time"]
    table = [
        [r.get("SID"), r.get("SERIAL"), r.get("USUARIO"), r.get("IDLE_MIN"),
         r.get("PCT_CPU"), r.get("MEM_MB"), r.get("MACHINE"), r.get("LOGON_TIME")]
        for r in rows
    ]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF004.2 ─────────────────────────────────────────────────────────────────
@tool
def get_total_inactive_sessions(_: str = "") -> str:
    """
    Devuelve el número total de sesiones inactivas u huérfanas
    (sin actividad > 30 minutos).
    No necesita parámetros.
    """
    total = q.get_total_inactive_sessions()
    return f"Total de sesiones inactivas (>30 min): {total}"


# ── RF004.3 ─────────────────────────────────────────────────────────────────
@tool
def get_inactive_sessions_by_user(username: str = "", limit: int = 5) -> str:
    """
    Dado un usuario, devuelve las sesiones inactivas u huérfanas
    (sin actividad > 30 minutos) asociadas a ese usuario.
    Parámetros:
    - username: usuario Oracle (coincidencia exacta). Si no se informa, consulta todos.
    - limit: número de resultados a devolver (por defecto 5).
    """
    normalized_username = (username or "").strip()
    rows = q.get_inactive_sessions_by_user(normalized_username, limit)
    if not rows:
        if normalized_username:
            return f"No se encontraron sesiones inactivas >30 min para el usuario '{normalized_username}'."
        return "No se encontraron sesiones inactivas superiores a 30 minutos."

    headers = ["SID", "SERIAL#", "Usuario", "Idle (min)", "% CPU", "Mem (MB)", "Máquina", "Logon Time"]
    table = [
        [r.get("SID"), r.get("SERIAL"), r.get("USUARIO"), r.get("IDLE_MIN"),
         r.get("PCT_CPU"), r.get("MEM_MB"), r.get("MACHINE"), r.get("LOGON_TIME")]
        for r in rows
    ]

    prefix = (
        f"Sesiones inactivas >30 min para usuario '{normalized_username}':\n"
        if normalized_username
        else "Sesiones inactivas >30 min (todos los usuarios):\n"
    )
    return prefix + tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF005 ─────────────────────────────────────────────────────────────────────
@tool
def get_blocking_sessions(limit: int = 5) -> str:
    """
    Devuelve las sesiones que están bloqueando a otras sesiones en la base de datos.
    Parámetro opcional 'limit': número de resultados a devolver (por defecto 5).
    """
    rows = q.get_blocking_sessions(limit)
    if not rows:
        return "No se detectaron sesiones bloqueantes en este momento."
    headers = ["SID", "SERIAL#", "Usuario", "Máquina"]
    table = [
        [r.get("SID"), r.get("SERIAL"), r.get("USUARIO"), r.get("MACHINE")]
        for r in rows
    ]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF005.1 ───────────────────────────────────────────────────────────────────
@tool
def get_blocking_sql(limit: int = 5) -> str:
    """
    Devuelve las SQLs que están ejecutando las sesiones bloqueantes, junto con
    el número de sesiones que bloquean.
    Parámetro opcional 'limit': número de resultados a devolver (por defecto 5).
    """
    rows = q.get_blocking_sql(limit)
    if not rows:
        return "No se detectaron SQLs de sesiones bloqueantes en este momento."
    headers = ["Blocker SID", "Usuario", "Sesiones Bloqueadas", "SQL ID", "SQL"]
    table = [
        [r.get("BLOCKER_SID"), r.get("USUARIO"), r.get("SESIONES_BLOQUEADAS"),
         r.get("SQL_ID"), str(r.get("SQL") or "")[:120]]
        for r in rows
    ]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF005.2 ─────────────────────────────────────────────────────────────────
@tool
def get_total_blocking_sql(_: str = "") -> str:
    """
    Devuelve el número total de SQL de sesiones bloqueantes.
    No necesita parámetros.
    """
    total = q.get_total_blocking_sql()
    return f"Total de SQL de sesiones bloqueantes: {total}"


# ── RF005.3 ─────────────────────────────────────────────────────────────────
@tool
def get_total_blocked_sessions(_: str = "") -> str:
    """
    Devuelve el número total de sesiones bloqueadas en este momento.
    No necesita parámetros.
    """
    total = q.get_total_blocked_sessions()
    return f"Total de sesiones bloqueadas: {total}"


# ── RF006 ─────────────────────────────────────────────────────────────────────
@tool
def generate_report(_: str = "") -> str:
    """
    Genera un informe completo en formato HTML con toda la información de rendimiento
    de la base de datos: CPU, top queries, sesiones, bloqueos, etc.
    Guarda el fichero en el directorio actual y devuelve la ruta.
    """
    from report.generator import generate
    path = generate()
    return f"Informe generado correctamente: {path}"


ALL_TOOLS = [
    get_cpu_usage,
    get_top_cpu_queries,
    get_top_cpu_sessions,
    get_users_with_inactive_sessions,
    get_inactive_sessions,
    get_total_inactive_sessions,
    get_inactive_sessions_by_user,
    get_blocking_sessions,
    get_blocking_sql,
    get_total_blocking_sql,
    get_total_blocked_sessions,
    generate_report,
]
