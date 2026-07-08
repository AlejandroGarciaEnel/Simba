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
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Recoger datos (con límite generoso para el informe)
    cpu_pct = q.get_cpu_usage()
    top_queries = q.get_top_cpu_queries(limit=10)
    top_sessions = q.get_top_cpu_sessions(limit=10)
    users_inactive = q.get_users_with_inactive_sessions(limit=10)
    inactive_sessions = q.get_inactive_sessions(limit=10)
    total_inactive_sessions = q.get_total_inactive_sessions()
    blocking = q.get_blocking_sessions(limit=10)
    blocking_sql = q.get_blocking_sql(limit=10)
    total_blocking_sql = q.get_total_blocking_sql()
    total_blocked_sessions = q.get_total_blocked_sessions()

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
        top_queries=top_queries,
        top_sessions=top_sessions,
        users_inactive=users_inactive,
        inactive_sessions=inactive_sessions,
        total_inactive_sessions=total_inactive_sessions,
        blocking=blocking,
        blocking_sql=blocking_sql,
        total_blocking_sql=total_blocking_sql,
        total_blocked_sessions=total_blocked_sessions,
    )

    filename = f"dbcheck_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    output_path = Path.cwd() / filename
    output_path.write_text(html, encoding="utf-8")
    return str(output_path)
