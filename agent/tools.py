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


# ── RF004.4 ─────────────────────────────────────────────────────────────────
@tool
def get_total_inactive_sessions_by_user(username: str) -> str:
    """
    Dado un usuario, devuelve el número total de sesiones inactivas u huérfanas
    (sin actividad > 30 minutos) asociadas a ese usuario.
    Parámetro obligatorio:
    - username: usuario Oracle (coincidencia exacta).
    """
    normalized_username = (username or "").strip()
    if not normalized_username:
        return "Debes indicar el parámetro obligatorio 'username'."
    total = q.get_total_inactive_sessions_by_user(normalized_username)
    return f"Total de sesiones inactivas >30 min para '{normalized_username}': {total}"


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


# ── RF007 ───────────────────────────────────────────────────────────────────
@tool
def get_database_summary(_: str = "") -> str:
    """
    Devuelve un resumen general de la base de datos con métricas clave.
    No necesita parámetros.
    """
    rows = q.get_database_summary()
    if not rows:
        return "No se encontraron métricas para el resumen general."
    headers = ["Métrica", "Valor"]
    table = [[r.get("METRIC_NAME"), r.get("VALUE")] for r in rows]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF008 ───────────────────────────────────────────────────────────────────
@tool
def get_metrics(_: str = "") -> str:
    """
    Devuelve métricas de rendimiento (foco en SGA) desde v$sysmetric.
    No necesita parámetros.
    """
    rows = q.get_metrics()
    if not rows:
        return "No se encontraron métricas de rendimiento para SGA."
    headers = ["Métrica", "Valor"]
    table = [[r.get("METRIC_NAME"), r.get("VALUE")] for r in rows]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF008.1 ─────────────────────────────────────────────────────────────────
@tool
def get_sga_info(_: str = "") -> str:
    """
    Devuelve el detalle del SGA desde v$sgainfo.
    No necesita parámetros.
    """
    rows = q.get_sga_info()
    if not rows:
        return "No se encontró información de SGA."
    headers = ["Nombre", "Bytes", "Resizables"]
    table = [[r.get("NAME"), r.get("BYTES"), r.get("RESIZEABLE")] for r in rows]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF009 ───────────────────────────────────────────────────────────────────
@tool
def get_users_with_active_sessions(limit: int = 5) -> str:
    """
    Devuelve los usuarios con más sesiones activas.
    Parámetro opcional 'limit': número de resultados a devolver (por defecto 5).
    """
    rows = q.get_users_with_active_sessions(limit)
    if not rows:
        return "No se encontraron usuarios con sesiones activas."
    headers = ["Usuario", "Sesiones Activas", "% CPU"]
    table = [[r.get("USUARIO"), r.get("SESIONES_ACTIVAS"), r.get("PCT_CPU")] for r in rows]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF009.1 ─────────────────────────────────────────────────────────────────
@tool
def get_active_sessions(limit: int = 5) -> str:
    """
    Devuelve el detalle de sesiones activas.
    Parámetro opcional 'limit': número de resultados a devolver (por defecto 5).
    """
    rows = q.get_active_sessions(limit)
    if not rows:
        return "No se encontraron sesiones activas."
    headers = ["SID", "SERIAL#", "Usuario", "SQL ID", "Tiempo Activo (seg)", "% CPU", "Mem (MB)", "Máquina", "Logon Time"]
    table = [
        [r.get("SID"), r.get("SERIAL"), r.get("USUARIO"), r.get("SQL_ID"), r.get("TIEMPO_ACTIVO_SEG"),
         r.get("PCT_CPU"), r.get("MEM_MB"), r.get("MACHINE"), r.get("LOGON_TIME")]
        for r in rows
    ]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF009.2 ─────────────────────────────────────────────────────────────────
@tool
def get_total_active_sessions(_: str = "") -> str:
    """
    Devuelve el número total de sesiones activas.
    No necesita parámetros.
    """
    total = q.get_total_active_sessions()
    return f"Total de sesiones activas: {total}"


# ── RF009.3 ─────────────────────────────────────────────────────────────────
@tool
def get_active_sessions_by_user(username: str, limit: int = 5) -> str:
    """
    Dado un usuario, devuelve el detalle de sus sesiones activas.
    Parámetros:
    - username: usuario Oracle (obligatorio)
    - limit: número de resultados a devolver (por defecto 5)
    """
    normalized_username = (username or "").strip()
    if not normalized_username:
        return "Debes indicar el parámetro obligatorio 'username'."
    rows = q.get_active_sessions_by_user(normalized_username, limit)
    if not rows:
        return f"No se encontraron sesiones activas para el usuario '{normalized_username}'."
    headers = ["SID", "SERIAL#", "Usuario", "SQL ID", "Tiempo Activo (seg)", "% CPU", "Mem (MB)", "Máquina", "Logon Time"]
    table = [
        [r.get("SID"), r.get("SERIAL"), r.get("USUARIO"), r.get("SQL_ID"), r.get("TIEMPO_ACTIVO_SEG"),
         r.get("PCT_CPU"), r.get("MEM_MB"), r.get("MACHINE"), r.get("LOGON_TIME")]
        for r in rows
    ]
    return (
        f"Sesiones activas para usuario '{normalized_username}':\n"
        + tabulate(table, headers=headers, tablefmt="rounded_outline")
    )


# ── RF009.4 ─────────────────────────────────────────────────────────────────
@tool
def get_total_active_sessions_by_user(username: str) -> str:
    """
    Dado un usuario, devuelve el número total de sesiones activas asociadas.
    Parámetro obligatorio:
    - username: usuario Oracle (coincidencia exacta)
    """
    normalized_username = (username or "").strip()
    if not normalized_username:
        return "Debes indicar el parámetro obligatorio 'username'."
    total = q.get_total_active_sessions_by_user(normalized_username)
    return f"Total de sesiones activas para '{normalized_username}': {total}"


# ── RF010 ───────────────────────────────────────────────────────────────────
@tool
def get_sql_info_by_sql_id(sql_id: str) -> str:
    """
    Devuelve la información de sesiones y SQL para un SQL ID específico.
    Parámetro obligatorio:
    - sql_id: identificador SQL (ejemplo: 5g7h2m3n1p9q0)
    """
    normalized_sql_id = (sql_id or "").strip()
    if not normalized_sql_id:
        return "Debes indicar el parámetro obligatorio 'sql_id'."
    rows = q.get_sql_info_by_sql_id(normalized_sql_id)
    if not rows:
        return f"No se encontró información para SQL ID '{normalized_sql_id}'."
    headers = ["SQL ID", "SID", "SERIAL#", "Usuario", "Estado", "Last Call", "Exec Start", "Wait (s)", "Máquina", "Módulo", "SQL"]
    table = [
        [r.get("SQL_ID"), r.get("SID"), r.get("SERIAL"), r.get("USERNAME"), r.get("STATUS"),
         r.get("LAST_CALL_ET"), r.get("SQL_EXEC_START"), r.get("SECONDS_IN_WAIT"),
         r.get("MACHINE"), r.get("MODULE"), str(r.get("SQL_TEXT") or "")[:120]]
        for r in rows
    ]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF011 ───────────────────────────────────────────────────────────────────
@tool
def get_sessions_by_program_and_machine(limit: int = 5) -> str:
    """
    Devuelve el número de sesiones por programa y máquina.
    Parámetro opcional 'limit': número de resultados a devolver (por defecto 5).
    """
    rows = q.get_sessions_by_program_and_machine(limit)
    if not rows:
        return "No se encontraron sesiones por programa y máquina."
    headers = ["Programa", "Máquina", "Sesiones"]
    table = [[r.get("PROGRAM"), r.get("MACHINE"), r.get("SESIONES")] for r in rows]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF012 ───────────────────────────────────────────────────────────────────
@tool
def get_sessions_by_user(limit: int = 5) -> str:
    """
    Devuelve el número de sesiones por usuario y estado.
    Parámetro opcional 'limit': número de resultados a devolver (por defecto 5).
    """
    rows = q.get_sessions_by_user(limit)
    if not rows:
        return "No se encontraron sesiones por usuario."
    headers = ["Usuario", "Estado", "Sesiones"]
    table = [[r.get("USERNAME"), r.get("STATUS"), r.get("SESIONES")] for r in rows]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF013 ───────────────────────────────────────────────────────────────────
@tool
def get_sessions_by_module(limit: int = 5) -> str:
    """
    Devuelve el número de sesiones por módulo.
    Parámetro opcional 'limit': número de resultados a devolver (por defecto 5).
    """
    rows = q.get_sessions_by_module(limit)
    if not rows:
        return "No se encontraron sesiones por módulo."
    headers = ["Módulo", "Sesiones"]
    table = [[r.get("MODULE"), r.get("SESIONES")] for r in rows]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF014 ───────────────────────────────────────────────────────────────────
@tool
def detect_pooling(threshold: int = 20, limit: int = 5) -> str:
    """
    Detecta posibles problemas de pooling con umbral configurable.
    Parámetros:
    - threshold: mínimo de sesiones para considerar pooling (por defecto 20)
    - limit: número de resultados (por defecto 5)
    """
    rows = q.detect_pooling(threshold=threshold, limit=limit)
    if not rows:
        return f"No se detectaron patrones de pooling por encima de {threshold} sesiones."
    headers = ["Programa", "Máquina", "Usuario", "Sesiones"]
    table = [[r.get("PROGRAM"), r.get("MACHINE"), r.get("USERNAME"), r.get("SESIONES")] for r in rows]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF015 ───────────────────────────────────────────────────────────────────
@tool
def get_latency_wait_metrics(_: str = "") -> str:
    """
    Devuelve métricas de latencia y esperas de la base de datos.
    No necesita parámetros.
    """
    rows = q.get_latency_wait_metrics()
    if not rows:
        return "No se encontraron métricas de latencia/waits. Es posible que no haya actividad de espera registrada en este momento o que la base de datos no exponga estas métricas."
    headers = ["Métrica", "Valor"]
    table = [[r.get("METRIC_NAME"), r.get("VALUE")] for r in rows]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF016 ───────────────────────────────────────────────────────────────────
@tool
def get_top_table_sizes(owner: str = "ENET", limit: int = 20) -> str:
    """
    Devuelve el top de tablas por tamaño para un esquema.
    Parámetros:
    - owner: esquema Oracle (por defecto ENET)
    - limit: número de resultados (por defecto 20)
    """
    rows = q.get_top_table_sizes(owner=owner, limit=limit)
    if not rows:
        return f"No se encontraron tablas para el esquema '{(owner or 'ENET').upper()}'."
    headers = ["Owner", "Tabla", "Tamaño MB", "Tamaño GB"]
    table = [[r.get("OWNER"), r.get("TABLA"), r.get("TAMANIO_MB"), r.get("TAMANIO_GB")] for r in rows]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF017 ───────────────────────────────────────────────────────────────────
@tool
def get_table_lock_detection(limit: int = 5) -> str:
    """
    Devuelve el detalle de bloqueos entre sesiones y objetos.
    Parámetro opcional 'limit': número de resultados a devolver (por defecto 5).
    """
    rows = q.get_table_lock_detection(limit)
    if not rows:
        return "No se detectaron bloqueos entre tablas en este momento."
    headers = ["Holder", "Recurso", "LType", "LMode", "Waiter", "SQL Waiter"]
    table = [
        [r.get("HOLDER"), r.get("RISORSA_ID"), r.get("LTYPE"), r.get("LMODE"),
         r.get("WAITER"), r.get("SQL_OF_WAITER")]
        for r in rows
    ]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF018 ───────────────────────────────────────────────────────────────────
@tool
def get_session_user_metrics(_: str = "") -> str:
    """
    Devuelve métricas agregadas de sesiones y usuarios desde v$sysmetric.
    No necesita parámetros.
    """
    rows = q.get_session_user_metrics()
    if not rows:
        return "No se encontraron métricas de sesiones/usuarios."
    headers = ["Métrica", "Valor"]
    table = [[r.get("METRIC_NAME"), r.get("VALUE")] for r in rows]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF019 ───────────────────────────────────────────────────────────────────
@tool
def get_sessions_by_user_status(_: str = "") -> str:
    """
    Devuelve el total de sesiones agrupadas por usuario y estado.
    No necesita parámetros.
    """
    rows = q.get_sessions_by_user_status()
    if not rows:
        return "No se encontraron sesiones por usuario/estado."
    headers = ["Usuario Oracle", "Estado", "Número Sesiones"]
    table = [[r.get("USUARIO_ORACLE"), r.get("STATUS"), r.get("NUMERO_SESIONES")] for r in rows]
    return tabulate(table, headers=headers, tablefmt="rounded_outline")


# ── RF020 ───────────────────────────────────────────────────────────────────
@tool
def get_total_sessions(_: str = "") -> str:
    """
    Devuelve el número total de sesiones conectadas en la base de datos,
    junto con cuántas están activas y cuántas llevan inactivas más de 30 minutos.
    No necesita parámetros.
    """
    total = q.get_total_sessions()
    activas = q.get_total_active_sessions()
    inactivas = q.get_total_inactive_sessions()
    return (
        f"Total de sesiones conectadas: {total}\n"
        f"  · Activas: {activas}\n"
        f"  · Inactivas más de 30 min: {inactivas}"
    )


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
    get_total_inactive_sessions_by_user,
    get_blocking_sessions,
    get_blocking_sql,
    get_total_blocking_sql,
    get_total_blocked_sessions,
    get_database_summary,
    get_metrics,
    get_sga_info,
    get_users_with_active_sessions,
    get_active_sessions,
    get_total_active_sessions,
    get_active_sessions_by_user,
    get_total_active_sessions_by_user,
    get_sql_info_by_sql_id,
    get_sessions_by_program_and_machine,
    get_sessions_by_user,
    get_sessions_by_module,
    detect_pooling,
    get_latency_wait_metrics,
    get_top_table_sizes,
    get_table_lock_detection,
    get_session_user_metrics,
    get_sessions_by_user_status,
    get_total_sessions,
    generate_report,
]
