"""
db/queries.py
Una función por RF. Cada función ejecuta su query y devuelve
una lista de diccionarios (columna → valor).
"""
from __future__ import annotations

import inspect
import logging
import os
import time
from typing import Any

from db.connection import get_connection

logger = logging.getLogger("db.queries")

# Timeout por query en milisegundos (cx_Oracle Connection.callTimeout); configurable
# vía SIMBA_DB_QUERY_TIMEOUT_MS para no bloquear el agente ante una BD lenta/colgada.
QUERY_TIMEOUT_MS = int(os.environ.get("SIMBA_DB_QUERY_TIMEOUT_MS", "5000"))

# Salvaguarda defensiva: nunca devolver más filas que esto, aunque una query
# sin límite explícito (p. ej. get_sga_info) devuelva un resultado inesperado.
HARD_ROW_LIMIT = 500
INACTIVE_LIST_MAX_ROWS = 20000  # el listado completo de inactivas no debe truncarse a 500


def _fetchall_as_dicts(sql: str, params: dict | None = None, *, max_rows: int = HARD_ROW_LIMIT) -> list[dict[str, Any]]:
    # nombre de la función RF llamante (db.queries.get_xxx), para identificar la query en los logs
    operation = inspect.stack()[1].function
    start = time.perf_counter()
    conn = get_connection()
    try:
        # en cx_Oracle el timeout es de la conexión (el cursor no tiene callTimeout y no se aplicaba)
        try:
            if conn.callTimeout != QUERY_TIMEOUT_MS:
                conn.callTimeout = QUERY_TIMEOUT_MS
        except AttributeError:
            logger.debug("connection_without_calltimeout op=%s", operation)
        with conn.cursor() as cur:
            cur.execute(sql, params or {})
            columns = [col[0] for col in cur.description]
            rows = cur.fetchall()
    except Exception:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.error("query_error op=%s duration_ms=%.1f", operation, duration_ms)
        raise

    truncated = len(rows) > max_rows
    if truncated:
        rows = rows[:max_rows]
        logger.warning("query_truncated op=%s rows=%d limit=%d", operation, len(rows), max_rows)

    duration_ms = (time.perf_counter() - start) * 1000
    logger.info("query_ok op=%s duration_ms=%.1f rows=%d", operation, duration_ms, len(rows))
    return [dict(zip(columns, row)) for row in rows]


# ── RF001 ─────────────────────────────────────────────────────────────────────
def get_cpu_usage_by_node() -> list[dict[str, Any]]:
    """Porcentaje de CPU de cada nodo del clúster (gv$osstat)."""
    sql = """
        SELECT b.inst_id AS nodo,
               ROUND(b.value * 100.0 / NULLIF(b.value + i.value, 0), 2) AS cpu_pct
        FROM gv$osstat b
        JOIN gv$osstat i ON i.inst_id = b.inst_id AND i.stat_name = 'IDLE_TIME'
        WHERE b.stat_name = 'BUSY_TIME'
        ORDER BY b.inst_id
    """
    return [{"nodo": int(r["NODO"]), "uso": float(r["CPU_PCT"] or 0.0)} for r in _fetchall_as_dicts(sql)]


def get_cpu_usage() -> float:
    """Porcentaje de CPU utilizado en el momento (RF001)."""
    sql = """
        SELECT
            ROUND(
                (SELECT value FROM v$osstat WHERE stat_name = 'BUSY_TIME') * 100.0 /
                NULLIF((SELECT value FROM v$osstat WHERE stat_name = 'IDLE_TIME') +
                       (SELECT value FROM v$osstat WHERE stat_name = 'BUSY_TIME'), 0),
                2
            ) AS cpu_pct
        FROM dual
    """
    rows = _fetchall_as_dicts(sql)
    return float(rows[0]["CPU_PCT"] or 0.0)


# ── RF002 ─────────────────────────────────────────────────────────────────────
def get_top_cpu_queries(limit: int = 5) -> list[dict[str, Any]]:
    """Queries que más CPU demandan (RF002)."""
    sql = """
        SELECT *
        FROM (
            SELECT
                s.username                                          AS usuario,
                q.executions                                        AS ejecuciones,
                ROUND(q.cpu_time * 100.0 /
                    NULLIF(SUM(q.cpu_time) OVER (), 0), 2)          AS pct_cpu,
                q.cpu_time,
                q.sql_fulltext                                      AS sql
            FROM v$sql q
            LEFT JOIN v$session s ON s.sql_id = q.sql_id
            WHERE q.cpu_time > 0
            ORDER BY q.cpu_time DESC
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"limit": limit})


# ── RF003 ─────────────────────────────────────────────────────────────────────
def get_top_cpu_sessions(limit: int = 5) -> list[dict[str, Any]]:
    """Sesiones que más CPU demandan (RF003)."""
    sql = """
        SELECT *
        FROM (
            SELECT
                s.sid,
                s.serial#                                           AS serial,
                s.username                                          AS usuario,
                sn.value                                            AS cpu_cs,
                ROUND(sn.value * 100.0 /
                    NULLIF(SUM(sn.value) OVER (), 0), 2)            AS pct_cpu
            FROM v$session s
            JOIN v$sesstat sn ON sn.sid = s.sid
            JOIN v$statname st ON st.statistic# = sn.statistic#
            WHERE st.name = 'CPU used by this session'
              AND s.status  = 'ACTIVE'
              AND sn.value  > 0
            ORDER BY sn.value DESC
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"limit": limit})


# ── RF004 ─────────────────────────────────────────────────────────────────────
def get_users_with_inactive_sessions(limit: int = 5) -> list[dict[str, Any]]:
    """Usuarios con más sesiones inactivas > 30 min (RF004)."""
    sql = """
        SELECT *
        FROM (
            SELECT
                s.username                                              AS usuario,
                COUNT(*)                                                AS sesiones_inactivas,
                ROUND(SUM(sn.value) * 100.0 /
                    NULLIF((SELECT SUM(v.value)
                            FROM v$sesstat v
                            JOIN v$statname n ON n.statistic# = v.statistic#
                            WHERE n.name = 'CPU used by this session'), 0), 2) AS pct_cpu
            FROM v$session s
            JOIN v$sesstat sn ON sn.sid = s.sid
            JOIN v$statname st ON st.statistic# = sn.statistic#
            WHERE s.status    = 'INACTIVE'
              AND s.last_call_et > 1800
              AND st.name     = 'CPU used by this session'
              AND s.username  IS NOT NULL
            GROUP BY s.username
            ORDER BY sesiones_inactivas DESC
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"limit": limit})


# ── RF004.1 ───────────────────────────────────────────────────────────────────
def get_inactive_sessions(limit: int = 5) -> list[dict[str, Any]]:
    """Sesiones inactivas / huérfanas > 30 min (RF004.1)."""
    sql = """
        SELECT *
        FROM (
            SELECT
                s.sid,
                s.serial#                                               AS serial,
                s.username                                              AS usuario,
                ROUND(s.last_call_et / 60, 1)                          AS idle_min,
                ROUND(cpu.value * 100.0 /
                    NULLIF((SELECT SUM(v.value)
                            FROM v$sesstat v
                            JOIN v$statname n ON n.statistic# = v.statistic#
                            WHERE n.name = 'CPU used by this session'), 0), 2) AS pct_cpu,
                ROUND(mem.value / 1024 / 1024, 2)                       AS mem_mb,
                s.machine,
                TO_CHAR(s.logon_time, 'YYYY-MM-DD HH24:MI:SS')         AS logon_time
            FROM v$session s
            JOIN v$sesstat cpu ON cpu.sid = s.sid
            JOIN v$statname cn  ON cn.statistic# = cpu.statistic#
            JOIN v$sesstat mem  ON mem.sid = s.sid
            JOIN v$statname mn  ON mn.statistic# = mem.statistic#
            WHERE s.status      = 'INACTIVE'
              AND s.last_call_et > 1800
              AND cn.name       = 'CPU used by this session'
              AND mn.name       = 'session pga memory'
              AND s.username    IS NOT NULL
            ORDER BY s.last_call_et DESC
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"limit": limit})


# ── RF004.2 ─────────────────────────────────────────────────────────────────
def get_total_inactive_sessions() -> int:
    """Número total de sesiones inactivas / huérfanas > 30 min (RF004.2)."""
    sql = """
        SELECT COUNT(*) AS total_inactivas
        FROM v$session s
        WHERE s.status = 'INACTIVE'
          AND s.last_call_et > 1800
    """
    rows = _fetchall_as_dicts(sql)
    if not rows:
        return 0
    return int(rows[0].get("TOTAL_INACTIVAS") or 0)


# ── RF004.3 ─────────────────────────────────────────────────────────────────
def get_inactive_sessions_by_user(username: str = "", limit: int = 5) -> list[dict[str, Any]]:
    """Sesiones inactivas > 30 min de un usuario (RF004.3)."""
    sql = """
        SELECT *
        FROM (
            SELECT
                s.sid,
                s.serial#                                               AS serial,
                s.username                                              AS usuario,
                ROUND(s.last_call_et / 60, 1)                          AS idle_min,
                ROUND(cpu.value * 100.0 /
                    NULLIF((SELECT SUM(v.value)
                            FROM v$sesstat v
                            JOIN v$statname n ON n.statistic# = v.statistic#
                            WHERE n.name = 'CPU used by this session'), 0), 2) AS pct_cpu,
                ROUND(mem.value / 1024 / 1024, 2)                       AS mem_mb,
                s.machine,
                TO_CHAR(s.logon_time, 'YYYY-MM-DD HH24:MI:SS')         AS logon_time
            FROM v$session s
            JOIN v$sesstat cpu ON cpu.sid = s.sid
            JOIN v$statname cn  ON cn.statistic# = cpu.statistic#
            JOIN v$sesstat mem  ON mem.sid = s.sid
            JOIN v$statname mn  ON mn.statistic# = mem.statistic#
            WHERE s.status      = 'INACTIVE'
              AND s.last_call_et > 1800
              AND cn.name       = 'CPU used by this session'
              AND mn.name       = 'session pga memory'
              AND s.username    IS NOT NULL
              AND (:username IS NULL OR :username = '' OR s.username = :username)
            ORDER BY s.last_call_et DESC
        )
        WHERE ROWNUM <= :limit
    """
    normalized_username = (username or "").strip()
    return _fetchall_as_dicts(sql, {"username": normalized_username, "limit": limit})


# ── RF005 ─────────────────────────────────────────────────────────────────────
def get_blocking_sessions(limit: int = 5) -> list[dict[str, Any]]:
    """Sesiones bloqueantes (RF005)."""
    sql = """
        SELECT *
        FROM (
            SELECT DISTINCT
                b.sid,
                b.serial#           AS serial,
                b.username          AS usuario,
                b.machine
            FROM v$lock lw
            JOIN v$lock lb   ON lb.id1 = lw.id1 AND lb.id2 = lw.id2
            JOIN v$session b ON b.sid  = lb.sid
            WHERE lw.block = 0
              AND lb.block = 1
            ORDER BY b.sid
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"limit": limit})


# ── RF005.1 ───────────────────────────────────────────────────────────────────
def get_blocking_sql(limit: int = 5) -> list[dict[str, Any]]:
    """SQL de las sesiones bloqueantes (RF005.1)."""
    sql = """
        SELECT *
        FROM (
            SELECT
                lb.sid                              AS blocker_sid,
                b.username                          AS usuario,
                COUNT(DISTINCT lw.sid)              AS sesiones_bloqueadas,
                b.sql_id,
                MAX(DBMS_LOB.SUBSTR(q.sql_fulltext, 4000, 1)) AS sql
            FROM v$lock lw
            JOIN v$lock   lb ON lb.id1 = lw.id1 AND lb.id2 = lw.id2
            JOIN v$session b  ON b.sid  = lb.sid
            LEFT JOIN v$sql q ON q.sql_id = b.sql_id
            WHERE lw.block = 0
              AND lb.block = 1
            GROUP BY lb.sid, b.username, b.sql_id
            ORDER BY sesiones_bloqueadas DESC
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"limit": limit})


# ── RF005.2 ─────────────────────────────────────────────────────────────────
def get_total_blocking_sql() -> int:
    """Número total de SQL de sesiones bloqueantes (RF005.2)."""
    sql = """
        SELECT COUNT(*) AS total_sql_bloqueantes
        FROM (
            SELECT
                lb.sid,
                b.sql_id
            FROM v$lock lw
            JOIN v$lock lb   ON lb.id1 = lw.id1 AND lb.id2 = lw.id2
            JOIN v$session b ON b.sid  = lb.sid
            WHERE lw.block = 0
              AND lb.block = 1
            GROUP BY lb.sid, b.sql_id
        )
    """
    rows = _fetchall_as_dicts(sql)
    if not rows:
        return 0
    return int(rows[0].get("TOTAL_SQL_BLOQUEANTES") or 0)


# ── RF005.3 ─────────────────────────────────────────────────────────────────
def get_total_blocked_sessions() -> int:
    """Número total de sesiones bloqueadas (RF005.3)."""
    sql = """
        SELECT COUNT(DISTINCT lw.sid) AS total_sesiones_bloqueadas
        FROM v$lock lw
        JOIN v$lock lb ON lb.id1 = lw.id1 AND lb.id2 = lw.id2
        WHERE lw.block = 0
          AND lb.block = 1
    """
    rows = _fetchall_as_dicts(sql)
    if not rows:
        return 0
    return int(rows[0].get("TOTAL_SESIONES_BLOQUEADAS") or 0)


# ── RF004.4 ─────────────────────────────────────────────────────────────────
def get_total_inactive_sessions_by_user(username: str) -> int:
    """Número total de sesiones inactivas > 30 min de un usuario (RF004.4)."""
    normalized_username = (username or "").strip()
    if not normalized_username:
        return 0

    sql = """
        SELECT COUNT(*) AS total_inactivas_usuario
        FROM v$session s
        WHERE s.status = 'INACTIVE'
          AND s.last_call_et > 1800
          AND s.username = :username
    """
    rows = _fetchall_as_dicts(sql, {"username": normalized_username})
    if not rows:
        return 0
    return int(rows[0].get("TOTAL_INACTIVAS_USUARIO") or 0)


# ── RF007 ───────────────────────────────────────────────────────────────────
def get_database_summary() -> list[dict[str, Any]]:
    """Resumen general de la BBDD (RF007)."""
    sql = """
        SELECT
            metric_name,
            ROUND(value, 2) AS value
        FROM v$sysmetric
        WHERE metric_name IN (
            'Host CPU Utilization (%)',
            'Database CPU Time Ratio (%)',
            'Average Active Sessions',
            'Current Logons Count',
            'PGA Cache Hit %',
            'Physical Reads Per Sec',
            'Physical Writes Per Sec'
        )
        ORDER BY metric_name
    """
    rows = _fetchall_as_dicts(sql)
    if rows:
        return rows

    # Fallback para instancias donde v$sysmetric/gv$sysmetric no exponen datos.
    fallback_sql = """
        SELECT 'Host CPU Utilization (%)' AS metric_name,
               ROUND(
                   (SELECT value FROM v$osstat WHERE stat_name = 'BUSY_TIME') * 100.0 /
                   NULLIF(
                       (SELECT value FROM v$osstat WHERE stat_name = 'IDLE_TIME') +
                       (SELECT value FROM v$osstat WHERE stat_name = 'BUSY_TIME'),
                       0
                   ),
                   2
               ) AS value
        FROM dual

        UNION ALL

        SELECT 'Database CPU Time Ratio (%)' AS metric_name,
               CAST(NULL AS NUMBER) AS value
        FROM dual

        UNION ALL

        SELECT 'Average Active Sessions' AS metric_name,
               ROUND((SELECT COUNT(*) FROM v$session WHERE status = 'ACTIVE'), 2) AS value
        FROM dual

        UNION ALL

        SELECT 'Current Logons Count' AS metric_name,
               ROUND((SELECT COUNT(*) FROM v$session), 2) AS value
        FROM dual

        UNION ALL

        SELECT 'PGA Cache Hit %' AS metric_name,
               ROUND(
                   (SELECT value FROM v$pgastat WHERE LOWER(name) = 'cache hit percentage'),
                   2
               ) AS value
        FROM dual

        UNION ALL

        SELECT 'Physical Reads Per Sec' AS metric_name,
               CAST(NULL AS NUMBER) AS value
        FROM dual

        UNION ALL

        SELECT 'Physical Writes Per Sec' AS metric_name,
               CAST(NULL AS NUMBER) AS value
        FROM dual

        ORDER BY metric_name
    """
    return _fetchall_as_dicts(fallback_sql)


# ── RF008 ───────────────────────────────────────────────────────────────────
def get_metrics() -> list[dict[str, Any]]:
    """Métricas de rendimiento (RF008)."""
    sql = """
        SELECT
            metric_name,
            ROUND(value, 2) AS value
        FROM v$sysmetric
        WHERE metric_name LIKE '%SGA%'
        ORDER BY metric_name
    """
    rows = _fetchall_as_dicts(sql)
    if rows:
        return rows

    # Fallback cuando v$sysmetric no devuelve datos en la instancia.
    fallback_sql = """
        SELECT
            name AS metric_name,
            ROUND(bytes / 1024 / 1024, 2) AS value
        FROM v$sgainfo
        WHERE bytes IS NOT NULL
        ORDER BY name
    """
    return _fetchall_as_dicts(fallback_sql)


# ── RF008.1 ─────────────────────────────────────────────────────────────────
def get_sga_info() -> list[dict[str, Any]]:
    """Información del SGA (RF008.1)."""
    sql = """
        SELECT *
        FROM v$sgainfo
    """
    return _fetchall_as_dicts(sql)


# ── RF009 ───────────────────────────────────────────────────────────────────
def get_users_with_active_sessions(limit: int = 5) -> list[dict[str, Any]]:
    """Usuarios con más sesiones activas (RF009)."""
    sql = """
        SELECT *
        FROM (
            SELECT
                s.username AS usuario,
                COUNT(*) AS sesiones_activas,
                ROUND(
                    SUM(sn.value) * 100.0 /
                    NULLIF(
                        (
                            SELECT SUM(v.value)
                            FROM v$sesstat v
                            JOIN v$statname n ON n.statistic# = v.statistic#
                            WHERE n.name = 'CPU used by this session'
                        ),
                        0
                    ),
                    2
                ) AS pct_cpu
            FROM v$session s
            JOIN v$sesstat sn ON sn.sid = s.sid
            JOIN v$statname st ON st.statistic# = sn.statistic#
            WHERE s.status = 'ACTIVE'
              AND st.name = 'CPU used by this session'
              AND s.username IS NOT NULL
            GROUP BY s.username
            ORDER BY sesiones_activas DESC
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"limit": limit})


# ── RF009.1 ─────────────────────────────────────────────────────────────────
def get_active_sessions(limit: int = 5) -> list[dict[str, Any]]:
    """Detalle de sesiones activas (RF009.1)."""
    sql = """
        SELECT *
        FROM (
            SELECT
                s.sid,
                s.serial# AS serial,
                s.username AS usuario,
                s.sql_id,
                s.last_call_et AS tiempo_activo_seg,
                ROUND(
                    cpu.value * 100.0 /
                    NULLIF(
                        (
                            SELECT SUM(v.value)
                            FROM v$sesstat v
                            JOIN v$statname n ON n.statistic# = v.statistic#
                            WHERE n.name = 'CPU used by this session'
                        ),
                        0
                    ),
                    2
                ) AS pct_cpu,
                ROUND(mem.value / 1024 / 1024, 2) AS mem_mb,
                s.machine,
                TO_CHAR(s.logon_time, 'YYYY-MM-DD HH24:MI:SS') AS logon_time
            FROM v$session s
            JOIN v$sesstat cpu ON cpu.sid = s.sid
            JOIN v$statname cn ON cn.statistic# = cpu.statistic#
            JOIN v$sesstat mem ON mem.sid = s.sid
            JOIN v$statname mn ON mn.statistic# = mem.statistic#
            WHERE s.status = 'ACTIVE'
              AND cn.name = 'CPU used by this session'
              AND mn.name = 'session pga memory'
              AND s.username IS NOT NULL
            ORDER BY s.last_call_et DESC
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"limit": limit})


# ── RF009.2 ─────────────────────────────────────────────────────────────────
def get_total_active_sessions() -> int:
    """Número total de sesiones activas (RF009.2)."""
    sql = """
        SELECT COUNT(*) AS total_activas
        FROM v$session s
        WHERE s.status = 'ACTIVE'
    """
    rows = _fetchall_as_dicts(sql)
    if not rows:
        return 0
    return int(rows[0].get("TOTAL_ACTIVAS") or 0)


# ── RF009.3 ─────────────────────────────────────────────────────────────────
def get_active_sessions_by_user(username: str, limit: int = 5) -> list[dict[str, Any]]:
    """Sesiones activas de un usuario (RF009.3)."""
    normalized_username = (username or "").strip()
    sql = """
        SELECT *
        FROM (
            SELECT
                s.sid,
                s.serial# AS serial,
                s.username AS usuario,
                s.sql_id,
                s.last_call_et AS tiempo_activo_seg,
                ROUND(
                    cpu.value * 100.0 /
                    NULLIF(
                        (
                            SELECT SUM(v.value)
                            FROM v$sesstat v
                            JOIN v$statname n ON n.statistic# = v.statistic#
                            WHERE n.name = 'CPU used by this session'
                        ),
                        0
                    ),
                    2
                ) AS pct_cpu,
                ROUND(mem.value / 1024 / 1024, 2) AS mem_mb,
                s.machine,
                TO_CHAR(s.logon_time, 'YYYY-MM-DD HH24:MI:SS') AS logon_time
            FROM v$session s
            JOIN v$sesstat cpu ON cpu.sid = s.sid
            JOIN v$statname cn ON cn.statistic# = cpu.statistic#
            JOIN v$sesstat mem ON mem.sid = s.sid
            JOIN v$statname mn ON mn.statistic# = mem.statistic#
            WHERE s.status = 'ACTIVE'
              AND cn.name = 'CPU used by this session'
              AND mn.name = 'session pga memory'
              AND s.username = :username
            ORDER BY s.last_call_et DESC
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"username": normalized_username, "limit": limit})


# ── RF009.4 ─────────────────────────────────────────────────────────────────
def get_total_active_sessions_by_user(username: str) -> int:
    """Número total de sesiones activas de un usuario (RF009.4)."""
    normalized_username = (username or "").strip()
    if not normalized_username:
        return 0

    sql = """
        SELECT COUNT(*) AS total_activas_usuario
        FROM v$session s
        WHERE s.status = 'ACTIVE'
          AND s.username = :username
    """
    rows = _fetchall_as_dicts(sql, {"username": normalized_username})
    if not rows:
        return 0
    return int(rows[0].get("TOTAL_ACTIVAS_USUARIO") or 0)


# ── RF010 ───────────────────────────────────────────────────────────────────
def get_sql_info_by_sql_id(sql_id: str) -> list[dict[str, Any]]:
    """Información de una SQL específica por SQL ID (RF010)."""
    normalized_sql_id = (sql_id or "").strip()
    if not normalized_sql_id:
        return []

    sql = """
        SELECT
            s.sql_id,
            s.sid,
            s.serial# AS serial,
            s.username,
            s.status,
            s.last_call_et,
            s.sql_exec_start,
            s.seconds_in_wait,
            s.machine,
            s.module,
            DBMS_LOB.SUBSTR(q.sql_text, 4000, 1) AS sql_text
        FROM v$session s
        JOIN v$sql q ON s.sql_id = q.sql_id
        WHERE s.sql_id = :sql_id
        ORDER BY s.sql_exec_start DESC NULLS LAST
    """
    return _fetchall_as_dicts(sql, {"sql_id": normalized_sql_id})


# ── RF011 ───────────────────────────────────────────────────────────────────
def get_sessions_by_program_and_machine(limit: int = 5) -> list[dict[str, Any]]:
    """Número de sesiones por programa y máquina (RF011)."""
    sql = """
        SELECT *
        FROM (
            SELECT
                program,
                machine,
                COUNT(*) AS sesiones
            FROM v$session
            WHERE type = 'USER'
            GROUP BY program, machine
            ORDER BY sesiones DESC
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"limit": limit})


# ── RF012 ───────────────────────────────────────────────────────────────────
def get_sessions_by_user(limit: int = 5) -> list[dict[str, Any]]:
    """Número de sesiones por usuario y estado (RF012)."""
    sql = """
        SELECT *
        FROM (
            SELECT
                username,
                status,
                COUNT(*) AS sesiones
            FROM v$session
            WHERE type = 'USER'
            GROUP BY username, status
            ORDER BY sesiones DESC
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"limit": limit})


# ── RF013 ───────────────────────────────────────────────────────────────────
def get_sessions_by_module(limit: int = 5) -> list[dict[str, Any]]:
    """Número de sesiones por módulo (RF013)."""
    sql = """
        SELECT *
        FROM (
            SELECT
                module,
                COUNT(*) AS sesiones
            FROM v$session
            WHERE module IS NOT NULL
            GROUP BY module
            ORDER BY sesiones DESC
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"limit": limit})


# ── RF014 ───────────────────────────────────────────────────────────────────
def detect_pooling(threshold: int = 20, limit: int = 5) -> list[dict[str, Any]]:
    """Detección de pooling por umbral de sesiones (RF014)."""
    sql = """
        SELECT *
        FROM (
            SELECT
                program,
                machine,
                username,
                COUNT(*) AS sesiones
            FROM v$session
            WHERE type = 'USER'
            GROUP BY program, machine, username
            HAVING COUNT(*) > :threshold
            ORDER BY sesiones DESC
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"threshold": threshold, "limit": limit})


# ── RF015 ───────────────────────────────────────────────────────────────────
def get_latency_wait_metrics() -> list[dict[str, Any]]:
    """Métricas de latencia y waits (RF015).

    Fuente primaria: v$sysmetric (intervalo de 60 s, GROUP_ID=2).
    Fallback: v$system_wait_class cuando la fuente primaria no devuelve filas,
    ya sea porque el Oracle en cuestión no genera esas métricas o porque en ese
    instante no hay actividad de espera registrada en el intervalo corto.
    """
    sql_sysmetric = """
        SELECT
            metric_name,
            ROUND(value, 2) AS value
        FROM v$sysmetric
        WHERE GROUP_ID = 2
          AND (metric_name LIKE '%Wait%' OR metric_name LIKE '%Latency%')
        ORDER BY metric_name
    """
    rows = _fetchall_as_dicts(sql_sysmetric)
    if rows:
        return rows

    # Fallback: clases de espera acumuladas (excluye Idle para no saturar)
    sql_wait_class = """
        SELECT
            wait_class      AS metric_name,
            ROUND(time_waited / 100, 2) AS value
        FROM v$system_wait_class
        WHERE wait_class != 'Idle'
        ORDER BY time_waited DESC
    """
    return _fetchall_as_dicts(sql_wait_class)


# ── RF016 ───────────────────────────────────────────────────────────────────
def get_top_table_sizes(owner: str = "ENET", limit: int = 20) -> list[dict[str, Any]]:
    """Top de tamaño de tablas en dba_segments (RF016)."""
    sql = """
        SELECT *
        FROM (
            SELECT
                owner,
                segment_name AS tabla,
                ROUND(SUM(bytes) / 1024 / 1024, 2) AS tamanio_mb,
                ROUND(SUM(bytes) / 1024 / 1024 / 1024, 4) AS tamanio_gb
            FROM dba_segments
            WHERE segment_type = 'TABLE'
              AND owner = :owner
            GROUP BY owner, segment_name
            ORDER BY tamanio_mb DESC
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"owner": (owner or "ENET").upper(), "limit": limit})


# ── RF017 ───────────────────────────────────────────────────────────────────
def get_table_lock_detection(limit: int = 5) -> list[dict[str, Any]]:
    """Detección de bloqueos entre tablas (RF017)."""
    sql = """
        SELECT *
        FROM (
            SELECT /*+ LEADING(lh) */
                'USERNAME==' || sh.username || '\n'
                    || 'SID,SER=' || sh.sid || ',' || sh.serial# || '\n'
                    || 'OSUSER=' || sh.osuser || '\n'
                    || 'PROG=' || sh.program AS holder,
                DECODE(
                    o.owner || '-',
                    '-', '*******',
                    o.owner || '.' || o.object_name || '\n'
                        || o.subobject_name || '(' || o.object_id || ')'
                ) AS risorsa_id,
                lh.type AS ltype,
                DECODE(
                    lh.lmode,
                    1, 'null',
                    2, 'RwShare',
                    3, 'RwExcl',
                    4, 'Share',
                    5, 'ShRwExcl',
                    6, 'Excl',
                    TO_CHAR(lh.lmode)
                ) AS lmode,
                'USERNAME=' || sw.username || '\n'
                    || 'SID,SER=' || sw.sid || ',' || sw.serial# || '\n'
                    || 'OSUSER=' || sw.osuser || '\n'
                    || 'PROG=' || sw.program AS waiter,
                SUBSTR(swa.sql_text, 1, 185) AS sql_of_waiter
            FROM v$sqlarea swa,
                 v$session sw,
                 v$lock lw,
                 dba_objects o,
                 v$session sh,
                 v$lock lh
            WHERE lh.request = 0
              AND lh.sid = sh.sid
              AND lh.id1 = lw.id1
              AND (lw.request != 0 OR lw.request IS NULL)
              AND lw.sid = sw.sid
              AND sw.lockwait IS NOT NULL
              AND sw.row_wait_obj# = o.object_id (+)
              AND sw.sql_hash_value = swa.hash_value
              AND sw.sql_address = swa.address
            ORDER BY holder, risorsa_id, ltype, lmode, waiter
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"limit": limit})


# ── RF018 ───────────────────────────────────────────────────────────────────
def get_session_user_metrics() -> list[dict[str, Any]]:
    """Métricas de sesiones y usuarios por sysmetric (RF018)."""
    sql = """
        SELECT
            metric_name,
            ROUND(value, 2) AS value
        FROM v$sysmetric
        WHERE metric_name LIKE '%Session%'
           OR metric_name LIKE '%User%'
        ORDER BY metric_name
    """
    return _fetchall_as_dicts(sql)


# ── RF019 ───────────────────────────────────────────────────────────────────
def get_sessions_by_user_status() -> list[dict[str, Any]]:
    """Totales de sesiones por usuario y estado (RF019)."""
    sql = """
        SELECT
            username AS usuario_oracle,
            status,
            COUNT(*) AS numero_sesiones
        FROM v$session
        GROUP BY username, status
        ORDER BY username, status
    """
    return _fetchall_as_dicts(sql)


# ── RF020 ───────────────────────────────────────────────────────────────────
def get_total_sessions() -> int:
    """Total de sesiones conectadas (RF020)."""
    sql = """
        SELECT COUNT(*) AS numero_sesiones
        FROM v$session
    """
    rows = _fetchall_as_dicts(sql)
    if not rows:
        return 0
    return int(rows[0].get("NUMERO_SESIONES") or 0)


# ── Revisión de estado (health check) ─────────────────────────────────────────
def get_tablespace_usage() -> list[dict[str, Any]]:
    """Uso de tablespaces: todos los TEMP/UNDO y los permanentes por encima del 70 %."""
    sql = """
        SELECT
            m.tablespace_name,
            t.contents,
            ROUND(m.used_percent, 2) AS used_pct
        FROM dba_tablespace_usage_metrics m
        JOIN dba_tablespaces t ON t.tablespace_name = m.tablespace_name
        WHERE t.contents IN ('TEMPORARY', 'UNDO')
           OR m.used_percent >= 70
        ORDER BY m.used_percent DESC
    """
    return _fetchall_as_dicts(sql)


def get_resource_limits() -> list[dict[str, Any]]:
    """Sesiones y procesos actuales frente a sus límites, por nodo del clúster (GV$).

    V$RESOURCE_LIMIT puede venir vacía para usuarios de solo monitorización.
    """
    sql = """
        SELECT
            'sessions (nodo ' || s.inst_id || ')' AS resource_name,
            s.n                                    AS current_utilization,
            TRIM(p.value)                          AS limit_value
        FROM (SELECT inst_id, COUNT(*) AS n FROM gv$session GROUP BY inst_id) s
        JOIN gv$parameter p ON p.inst_id = s.inst_id AND p.name = 'sessions'
        UNION ALL
        SELECT
            'processes (nodo ' || s.inst_id || ')',
            s.n,
            TRIM(p.value)
        FROM (SELECT inst_id, COUNT(*) AS n FROM gv$process GROUP BY inst_id) s
        JOIN gv$parameter p ON p.inst_id = s.inst_id AND p.name = 'processes'
    """
    return _fetchall_as_dicts(sql)


def get_blocked_waits(limit: int = 10) -> list[dict[str, Any]]:
    """Sesiones bloqueadas con el tiempo que llevan esperando y el estado del bloqueante."""
    sql = """
        SELECT *
        FROM (
            SELECT
                w.sid                  AS sid_bloqueada,
                w.username             AS usuario_bloqueado,
                w.event                AS evento,
                w.seconds_in_wait      AS segundos_espera,
                b.sid                  AS sid_bloqueante,
                b.username             AS usuario_bloqueante,
                b.status               AS estado_bloqueante,
                b.machine              AS maquina_bloqueante,
                b.program              AS programa_bloqueante,
                b.last_call_et         AS segundos_ultima_llamada
            FROM gv$session w
            JOIN gv$session b ON b.inst_id = w.blocking_instance AND b.sid = w.blocking_session
            WHERE w.blocking_session IS NOT NULL
            ORDER BY w.seconds_in_wait DESC
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"limit": limit})


def get_blocked_session_list(limit: int = 300) -> list[dict[str, Any]]:
    """Todas las sesiones bloqueadas (cualquier nodo del RAC) con su bloqueante directo y final. Solo SELECT."""
    sql = """
        SELECT
            w.inst_id AS instancia, w.sid AS sid, w.serial# AS serial,
            w.username AS usuario, w.machine AS maquina, w.program AS programa, w.module AS modulo,
            w.event AS evento, w.seconds_in_wait AS segundos_espera,
            NVL(w.sql_id, w.prev_sql_id) AS sql_id,
            w.blocking_instance AS inst_bloqueante, w.blocking_session AS sid_bloqueante,
            w.final_blocking_instance AS inst_raiz, w.final_blocking_session AS sid_raiz,
            w.row_wait_obj# AS obj_id
        FROM gv$session w
        WHERE w.blocking_session IS NOT NULL
        ORDER BY w.seconds_in_wait DESC
        FETCH FIRST :limit ROWS ONLY
    """
    return _fetchall_as_dicts(sql, {"limit": limit})


def get_object_names(object_ids: list[int]) -> dict[int, str]:
    """Nombres OWNER.OBJETO de unos pocos object_id (consulta acotada en lugar de un join sobre dba_objects)."""
    ids = sorted({int(i) for i in object_ids if i is not None and int(i) > 0})[:100]
    if not ids:
        return {}
    binds = {f"o{n}": v for n, v in enumerate(ids)}
    sql = f"SELECT object_id, owner || '.' || object_name AS nombre FROM dba_objects WHERE object_id IN ({', '.join(':' + k for k in binds)})"
    return {int(r["OBJECT_ID"]): r["NOMBRE"] for r in _fetchall_as_dicts(sql, binds)}


def get_sql_texts(sql_ids: list[str]) -> dict[str, str]:
    """Texto (200 primeros caracteres) de unos pocos SQL_ID, en una sola consulta sobre gv$sqlarea."""
    ids = sorted({i for i in sql_ids if i})[:40]
    if not ids:
        return {}
    binds = {f"s{n}": v for n, v in enumerate(ids)}
    sql = ("SELECT sql_id, MAX(SUBSTR(sql_text, 1, 200)) AS texto FROM gv$sqlarea "
           f"WHERE sql_id IN ({', '.join(':' + k for k in binds)}) GROUP BY sql_id")
    return {r["SQL_ID"]: r["TEXTO"] for r in _fetchall_as_dicts(sql, binds)}


def get_root_blockers(limit: int = 10) -> list[dict[str, Any]]:
    """
    Sesiones que originan los bloqueos (bloqueante final de la cadena, en cualquier nodo del RAC), con quién
    son, qué SQL ejecutan o ejecutaron por última vez, a cuántas sesiones bloquean y sobre qué objeto.
    """
    sql = """
        WITH esperas AS (
            SELECT final_blocking_instance AS inst_b, final_blocking_session AS sid_b,
                   seconds_in_wait, event, row_wait_obj#
            FROM gv$session
            WHERE final_blocking_session IS NOT NULL
              AND final_blocking_session_status = 'VALID'
        ),
        agrupado AS (
            SELECT inst_b, sid_b,
                   COUNT(*)                                                        AS bloqueadas,
                   MAX(seconds_in_wait)                                            AS max_espera,
                   MAX(event)          KEEP (DENSE_RANK LAST ORDER BY seconds_in_wait) AS evento,
                   MAX(row_wait_obj#)  KEEP (DENSE_RANK LAST ORDER BY seconds_in_wait) AS obj_id
            FROM esperas
            GROUP BY inst_b, sid_b
        )
        SELECT
            b.inst_id                                   AS instancia,
            b.sid                                       AS sid,
            b.serial#                                   AS serial,
            b.username                                  AS usuario,
            b.osuser                                    AS usuario_so,
            b.machine                                   AS maquina,
            b.program                                   AS programa,
            b.module                                    AS modulo,
            b.status                                    AS estado,
            b.last_call_et                              AS segundos_ultima_llamada,
            NVL(b.sql_id, b.prev_sql_id)                AS sql_id,
            CASE WHEN b.sql_id IS NULL THEN 'última ejecutada' ELSE 'en ejecución' END AS tipo_sql,
            (SELECT SUBSTR(s.sql_text, 1, 200) FROM gv$sql s
              WHERE s.inst_id = b.inst_id AND s.sql_id = NVL(b.sql_id, b.prev_sql_id) AND ROWNUM = 1) AS sql_texto,
            a.bloqueadas                                AS sesiones_bloqueadas,
            a.max_espera                                AS segundos_espera,
            a.evento                                    AS evento,
            o.owner || '.' || o.object_name             AS objeto
        FROM agrupado a
        JOIN gv$session b ON b.inst_id = a.inst_b AND b.sid = a.sid_b
        LEFT JOIN dba_objects o ON o.object_id = a.obj_id
        ORDER BY a.max_espera DESC
        FETCH FIRST :limit ROWS ONLY
    """
    return _fetchall_as_dicts(sql, {"limit": limit})


def get_current_wait_events(limit: int = 5) -> list[dict[str, Any]]:
    """Eventos de espera de las sesiones de usuario activas ahora mismo."""
    sql = """
        SELECT *
        FROM (
            SELECT event AS evento, wait_class AS clase, COUNT(*) AS sesiones
            FROM gv$session
            WHERE type = 'USER'
              AND status = 'ACTIVE'
              AND wait_class <> 'Idle'
            GROUP BY event, wait_class
            ORDER BY COUNT(*) DESC
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"limit": limit})


def get_long_operations(limit: int = 5) -> list[dict[str, Any]]:
    """Operaciones largas en curso (V$SESSION_LONGOPS)."""
    sql = """
        SELECT *
        FROM (
            SELECT
                sid,
                username                AS usuario,
                opname                  AS operacion,
                ROUND(sofar * 100 / NULLIF(totalwork, 0), 1) AS pct_completado,
                elapsed_seconds         AS segundos_transcurridos,
                time_remaining          AS segundos_restantes
            FROM gv$session_longops
            WHERE time_remaining > 0
            ORDER BY elapsed_seconds DESC
        )
        WHERE ROWNUM <= :limit
    """
    return _fetchall_as_dicts(sql, {"limit": limit})


def get_recent_problems(hours: int = 1) -> list[dict[str, Any]]:
    """
    Problemas de Oracle (ADR, V$DIAG_PROBLEM) con incidencias en las últimas horas, con la fecha en que
    apareció cada uno por primera vez para distinguir lo nuevo de lo recurrente. Solo la instancia conectada.
    Sustituye a V$DIAG_ALERT_EXT, que lee todo el alert log y en este entorno supera el minuto.
    """
    sql = """
        SELECT
            problem_key                                              AS problema,
            TO_CHAR(firstinc_time, 'YYYY-MM-DD HH24:MI:SS')          AS primera_vez,
            TO_CHAR(lastinc_time, 'YYYY-MM-DD HH24:MI:SS')           AS ultima_vez,
            ROUND(SYSDATE - CAST(firstinc_time AS DATE), 1)          AS dias_desde_primera
        FROM v$diag_problem
        WHERE lastinc_time > SYSTIMESTAMP - NUMTODSINTERVAL(:horas, 'HOUR')
        ORDER BY lastinc_time DESC
    """
    return _fetchall_as_dicts(sql, {"horas": hours})


def get_cluster_inactive_sessions() -> int:
    """Sesiones inactivas > 30 min sumando todos los nodos del clúster (GV$)."""
    sql = """
        SELECT COUNT(*) AS total_inactivas
        FROM gv$session s
        WHERE s.status = 'INACTIVE'
          AND s.last_call_et > 1800
    """
    rows = _fetchall_as_dicts(sql)
    return int(rows[0].get("TOTAL_INACTIVAS") or 0) if rows else 0


def get_cluster_inactive_session_list() -> list[dict[str, Any]]:
    """Detalle de las sesiones inactivas > 30 min de todos los nodos (GV$), la más antigua primero."""
    sql = """
        SELECT s.inst_id                                  AS instancia,
               s.sid,
               s.serial#                                  AS serial,
               s.username                                 AS usuario,
               s.osuser                                   AS usuario_so,
               s.machine                                  AS maquina,
               s.program                                  AS programa,
               s.module                                   AS modulo,
               s.last_call_et                             AS inactiva_s,
               TO_CHAR(s.logon_time, 'YYYY-MM-DD HH24:MI:SS') AS conexion
        FROM gv$session s
        WHERE s.status = 'INACTIVE'
          AND s.last_call_et > 1800
          AND s.type = 'USER'
        ORDER BY s.last_call_et DESC
    """
    return _fetchall_as_dicts(sql, max_rows=INACTIVE_LIST_MAX_ROWS)


# ── Análisis de una SQL concreta (solo DBA en la web) ─────────────────────────
_PLAN_TABLES_CTE = """
    with objs as (
        select object_owner owner, object_name name, object_type from gv$sql_plan
         where sql_id = :sql_id and object_owner is not null
        union
        select object_owner, object_name, object_type from dba_hist_sql_plan
         where sql_id = :sql_id and dbid = (select dbid from v$database) and object_owner is not null
    ), tabs as (
        select owner, name table_name from objs where object_type like 'TABLE%'
        union
        select i.table_owner, i.table_name
          from objs o join dba_indexes i on i.owner = o.owner and i.index_name = o.name
         where o.object_type like 'INDEX%'
    )"""


def get_sql_cursors(sql_id: str) -> list[dict[str, Any]]:
    """Cursores en memoria de una SQL_ID en todas las instancias (GV$SQL)."""
    sql = """
        select inst_id instancia, child_number hijo, plan_hash_value,
               parsing_schema_name esquema, module modulo, executions ejecuciones,
               round(elapsed_time / 1e6, 1) elapsed_s, round(cpu_time / 1e6, 1) cpu_s,
               buffer_gets lecturas, disk_reads lecturas_disco, rows_processed filas,
               optimizer_cost coste, sql_profile, sql_plan_baseline,
               is_bind_sensitive, is_bind_aware, last_active_time ultima_actividad,
               dbms_lob.substr(sql_fulltext, 2000, 1) sql_texto
          from gv$sql
         where sql_id = :sql_id
         order by last_active_time desc nulls last
         fetch first 50 rows only"""
    return _fetchall_as_dicts(sql, {"sql_id": sql_id})


def get_sql_plan_history(sql_id: str, days: int = 30) -> list[dict[str, Any]]:
    """Rendimiento por plan de ejecución en el AWR de los últimos días."""
    sql = """
        select st.plan_hash_value,
               sum(st.executions_delta) ejecuciones,
               round(sum(st.elapsed_time_delta) / nullif(sum(st.executions_delta), 0) / 1e6, 4) elapsed_s_ejec,
               round(sum(st.cpu_time_delta) / 1e6 / 3600, 2) cpu_h,
               round(sum(st.buffer_gets_delta) / nullif(sum(st.executions_delta), 0)) lecturas_ejec,
               round(sum(st.rows_processed_delta) / nullif(sum(st.executions_delta), 0), 1) filas_ejec,
               min(sn.begin_interval_time) primera_vez, max(sn.end_interval_time) ultima_vez
          from dba_hist_sqlstat st
          join dba_hist_snapshot sn
            on sn.snap_id = st.snap_id and sn.dbid = st.dbid and sn.instance_number = st.instance_number
         where st.sql_id = :sql_id
           and st.dbid = (select dbid from v$database)
           and sn.begin_interval_time > systimestamp - numtodsinterval(:days, 'DAY')
         group by st.plan_hash_value
         order by cpu_h desc nulls last
         fetch first 20 rows only"""
    return _fetchall_as_dicts(sql, {"sql_id": sql_id, "days": days})


def get_sql_daily_trend(sql_id: str, days: int = 14) -> list[dict[str, Any]]:
    """Evolución diaria (AWR) de ejecuciones, tiempo por ejecución y planes usados."""
    sql = """
        select trunc(sn.begin_interval_time) dia,
               sum(st.executions_delta) ejecuciones,
               round(sum(st.elapsed_time_delta) / nullif(sum(st.executions_delta), 0) / 1e6, 4) elapsed_s_ejec,
               round(sum(st.cpu_time_delta) / 1e6 / 3600, 2) cpu_h,
               count(distinct st.plan_hash_value) planes
          from dba_hist_sqlstat st
          join dba_hist_snapshot sn
            on sn.snap_id = st.snap_id and sn.dbid = st.dbid and sn.instance_number = st.instance_number
         where st.sql_id = :sql_id
           and st.dbid = (select dbid from v$database)
           and sn.begin_interval_time > systimestamp - numtodsinterval(:days, 'DAY')
         group by trunc(sn.begin_interval_time)
         order by dia"""
    return _fetchall_as_dicts(sql, {"sql_id": sql_id, "days": days})


def get_sql_plan_lines(sql_id: str, plan_hash_value: int) -> list[dict[str, Any]]:
    """Líneas de un plan: de memoria (GV$SQL_PLAN) si está, si no del AWR."""
    sql = """
        with mem as (
            select inst_id, child_number from gv$sql_plan
             where sql_id = :sql_id and plan_hash_value = :phv and id = 0
             fetch first 1 rows only
        )
        select 'memoria' origen, p.id, p.depth profundidad, p.operation operacion, p.options opciones,
               p.object_owner propietario, p.object_name objeto, p.cost coste, p.cardinality filas_estimadas,
               substr(p.access_predicates, 1, 400) acceso, substr(p.filter_predicates, 1, 400) filtro
          from gv$sql_plan p join mem m on p.inst_id = m.inst_id and p.child_number = m.child_number
         where p.sql_id = :sql_id and p.plan_hash_value = :phv
        union all
        select 'awr', h.id, h.depth, h.operation, h.options, h.object_owner, h.object_name, h.cost, h.cardinality,
               substr(h.access_predicates, 1, 400), substr(h.filter_predicates, 1, 400)
          from dba_hist_sql_plan h
         where h.sql_id = :sql_id and h.plan_hash_value = :phv and h.dbid = (select dbid from v$database)
           and not exists (select 1 from mem)
         order by 2
         fetch first 300 rows only"""
    return _fetchall_as_dicts(sql, {"sql_id": sql_id, "phv": plan_hash_value})


def get_sql_table_stats(sql_id: str) -> list[dict[str, Any]]:
    """Estadísticas de las tablas que aparecen en los planes de la SQL."""
    sql = _PLAN_TABLES_CTE + """
        select t.owner propietario, t.table_name tabla, s.num_rows filas, s.blocks bloques,
               s.last_analyzed ultimo_analisis, s.stale_stats obsoletas, s.stattype_locked bloqueadas,
               (select m.inserts + m.updates + m.deletes from dba_tab_modifications m
                 where m.table_owner = t.owner and m.table_name = t.table_name and m.partition_name is null
                   and rownum = 1) modificaciones
          from tabs t
          join dba_tab_statistics s
            on s.owner = t.owner and s.table_name = t.table_name and s.object_type = 'TABLE'
         order by s.num_rows desc nulls last
         fetch first 30 rows only"""
    return _fetchall_as_dicts(sql, {"sql_id": sql_id})


def get_sql_table_indexes(sql_id: str) -> list[dict[str, Any]]:
    """Índices de las tablas que usa la SQL, con sus columnas y estado."""
    sql = _PLAN_TABLES_CTE + """
        select i.table_owner propietario, i.table_name tabla, i.index_name indice, i.uniqueness unicidad,
               i.status estado, i.visibility visibilidad, i.last_analyzed ultimo_analisis,
               (select listagg(c.column_name, ', ') within group (order by c.column_position)
                  from dba_ind_columns c where c.index_owner = i.owner and c.index_name = i.index_name) columnas
          from dba_indexes i
          join tabs t on i.table_owner = t.owner and i.table_name = t.table_name
         order by i.table_name, i.index_name
         fetch first 80 rows only"""
    return _fetchall_as_dicts(sql, {"sql_id": sql_id})


def get_plsql_child_sqls(sql_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """SQL que ejecuta por dentro una llamada PL/SQL, según el ASH en memoria (últimas horas)."""
    sql = """
        select a.sql_id, count(*) muestras,
               (select substr(max(s.sql_text), 1, 200) from gv$sql s where s.sql_id = a.sql_id) sql_texto
          from gv$active_session_history a
         where a.top_level_sql_id = :sql_id and a.sql_id is not null and a.sql_id <> :sql_id
         group by a.sql_id
         order by muestras desc
         fetch first :limit rows only"""
    return _fetchall_as_dicts(sql, {"sql_id": sql_id, "limit": limit})
