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
