"""
db/queries.py
Una función por RF. Cada función ejecuta su query y devuelve
una lista de diccionarios (columna → valor).
"""
from __future__ import annotations

from typing import Any

from db.connection import get_connection


def _fetchall_as_dicts(sql: str, params: dict | None = None) -> list[dict[str, Any]]:
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(sql, params or {})
        columns = [col[0] for col in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


# ── RF001 ─────────────────────────────────────────────────────────────────────
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
