"""
report/generator.py
Recoge datos de todas las queries y renderiza el informe HTML con Jinja2.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

import db.queries as q


def generate() -> str:
    """Genera el informe HTML y devuelve la ruta del fichero creado."""
    env_name = os.environ.get("DB_SERVICE", "BBDD")
    now = datetime.now()
    generated_at = now.strftime("%d-%m-%Y %H:%M")

    # Recoger datos del apartado 5 (solo RF requeridos)
    # Apartado 1
    cpu_pct = q.get_cpu_usage()
    metrics = q.get_metrics()[:5]
    sga_info = q.get_sga_info()[:5]
    latency_wait_metrics = q.get_latency_wait_metrics()[:5]

    # Apartado 2
    total_sessions = q.get_total_sessions()
    total_active_sessions = q.get_total_active_sessions()
    total_inactive_sessions = q.get_total_inactive_sessions()
    total_blocking_sql = q.get_total_blocking_sql()
    total_blocked_sessions = q.get_total_blocked_sessions()

    # Apartado 3
    users_active = q.get_users_with_active_sessions(limit=5)
    users_inactive = q.get_users_with_inactive_sessions(limit=5)

    # Apartado 4
    blocking = q.get_blocking_sessions(limit=5)
    blocking_sql = q.get_blocking_sql(limit=5)
    table_lock_detection = q.get_table_lock_detection(limit=5)

    # Apartado 5
    sessions_by_program_machine = q.get_sessions_by_program_and_machine(limit=5)
    sessions_by_user = q.get_sessions_by_user(limit=5)
    sessions_by_module = q.get_sessions_by_module(limit=5)
    pooling = q.detect_pooling(threshold=20, limit=5)
    top_table_sizes = q.get_top_table_sizes(owner=os.environ.get("REPORT_OWNER", "ENET"), limit=5)
    session_user_metrics = q.get_session_user_metrics()[:5]
    sessions_by_user_status = q.get_sessions_by_user_status()[:5]

    # Estado de CPU para badge
    if cpu_pct < 60:
        cpu_status = "green"
        cpu_label = "Verde"
    elif cpu_pct < 85:
        cpu_status = "yellow"
        cpu_label = "Amarillo"
    else:
        cpu_status = "red"
        cpu_label = "Rojo"

    template_dir = Path(__file__).parent
    jinja_env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=True,
    )
    template = jinja_env.get_template("template.html")

    html = template.render(
        env_name=env_name,
        generated_at=generated_at,
        cpu_pct=f"{cpu_pct:.2f}%",
        cpu_status=cpu_status,
        cpu_label=cpu_label,
        metrics=metrics,
        sga_info=sga_info,
        latency_wait_metrics=latency_wait_metrics,
        total_sessions=total_sessions,
        total_active_sessions=total_active_sessions,
        users_inactive=users_inactive,
        users_active=users_active,
        total_inactive_sessions=total_inactive_sessions,
        blocking=blocking,
        blocking_sql=blocking_sql,
        total_blocking_sql=total_blocking_sql,
        total_blocked_sessions=total_blocked_sessions,
        table_lock_detection=table_lock_detection,
        sessions_by_program_machine=sessions_by_program_machine,
        sessions_by_user=sessions_by_user,
        sessions_by_module=sessions_by_module,
        pooling=pooling,
        top_table_sizes=top_table_sizes,
        session_user_metrics=session_user_metrics,
        sessions_by_user_status=sessions_by_user_status,
    )

    year_three = now.strftime("%Y")[1:]
    filename = f"dbCheck_{now.strftime('%d-%m')}-{year_three}_{now.strftime('%H-%M')}.html"
    output_path = Path.cwd() / filename
    output_path.write_text(html, encoding="utf-8")
    return str(output_path)
