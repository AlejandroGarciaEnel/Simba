"""
report/awr_followup.py
Seguimiento en vivo de un análisis AWR (RF021): tras resumir el informe se ejecutan en la BD
las consultas de solo lectura asociadas a sus hallazgos, se comparan los SQL IDs del AWR con
el estado actual y se añade el resultado al resumen.

Seguridad: el contenido del AWR (no confiable) solo selecciona áreas y SQL IDs con formato
Oracle válido; las acciones ejecutables salen exclusivamente de la lista blanca ALLOWED_ACTIONS.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tabulate import tabulate

import db.queries as q
from db.connection import get_connection
from report.awr_analyzer import GENERIC_FOLLOWUP, AwrAnalysis, parse_awr_report, render_summary

logger = logging.getLogger("report.awr_followup")

MAX_ACTIONS = 12

# acción -> (descripción, argumentos fijos). Son herramientas de agent.tools de solo lectura.
ALLOWED_ACTIONS: dict[str, tuple[str, dict[str, Any]]] = {
    "get_cpu_usage": ("CPU actual (RF001)", {}),
    "get_top_cpu_sessions": ("Sesiones con más CPU (RF003)", {"limit": 5}),
    "get_blocking_sessions": ("Sesiones bloqueantes (RF005)", {"limit": 5}),
    "get_table_lock_detection": ("Bloqueos entre tablas (RF017)", {"limit": 5}),
    "get_latency_wait_metrics": ("Latencia y esperas (RF015)", {}),
    "detect_pooling": ("Patrones de pooling (RF014)", {"threshold": 20, "limit": 5}),
    "get_total_sessions": ("Total de sesiones (RF020)", {}),
    "get_metrics": ("Métricas de rendimiento (RF008)", {}),
    "get_sga_info": ("Detalle de SGA (RF008.1)", {}),
    "get_database_summary": ("Resumen general de la BD (RF007)", {}),
}


def followup_enabled() -> bool:
    """Interruptor SIMBA_AWR_FOLLOWUP (activo por defecto) para la subida web de informes."""
    return os.environ.get("SIMBA_AWR_FOLLOWUP", "true").strip().lower() not in ("false", "0", "no")


def _env_number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _budget_seconds() -> float:
    return max(1.0, _env_number("SIMBA_AWR_FOLLOWUP_BUDGET_S", 30))


@dataclass
class FollowupSection:
    title: str
    body: str
    ok: bool = True


@dataclass
class FollowupResult:
    available: bool
    sections: list[FollowupSection] = field(default_factory=list)
    conclusion: str = ""
    notes: list[str] = field(default_factory=list)

    def render_text(self) -> str:
        if not self.available:
            return "\n".join(self.notes)
        lines = ["=== Contraste en vivo con la BD (ejecutado tras el análisis AWR) ==="]
        for section in self.sections:
            lines.append(f"\n▸ {section.title}\n{section.body}")
        lines.extend(self.notes)
        if self.conclusion:
            lines.append(f"\nConclusión del contraste: {self.conclusion}")
        return "\n".join(lines)


@dataclass
class AwrOutcome:
    summary: str
    followup: str = ""

    @property
    def message(self) -> str:
        return f"{self.summary}\n\n{self.followup}" if self.followup else self.summary


class _Budget:
    def __init__(self) -> None:
        self.deadline = time.monotonic() + _budget_seconds()
        self.executed = 0
        self.failed = 0

    def exhausted(self) -> bool:
        return self.executed >= MAX_ACTIONS or time.monotonic() > self.deadline


def _run_action(name: str) -> str:
    import agent.tools as agent_tools

    _, args = ALLOWED_ACTIONS[name]
    return str(getattr(agent_tools, name).invoke(dict(args)))


def _compare_top_sql(analysis: AwrAnalysis, budget: _Budget) -> tuple[FollowupSection, int, int]:
    """Contrasta los SQL IDs del AWR con el top de CPU actual (RF002) y las sesiones (RF010)."""
    live_cpu_ids = {row.get("SQL_ID") for row in q.get_top_cpu_queries(limit=5)}
    budget.executed += 1
    rows: list[list[Any]] = []
    still_live = 0
    for item in analysis.top_sql:
        if budget.exhausted():
            break
        sessions = q.get_sql_info_by_sql_id(item.sql_id)
        budget.executed += 1
        if item.sql_id in live_cpu_ids:
            state = "En el top de CPU actual"
        elif sessions:
            state = f"Con {len(sessions)} sesión(es) ahora"
        else:
            state = "No visible en vivo"
        if state != "No visible en vivo":
            still_live += 1
        rows.append([item.sql_id, item.elapsed_s, item.execs, item.pct_db_time, state])
    headers = ["SQL ID", "Elapsed AWR (s)", "Execs AWR", "% DB time", "Estado en vivo"]
    body = tabulate(rows, headers=headers, tablefmt="rounded_outline", disable_numparse=True)
    return FollowupSection("SQL del AWR frente al estado actual (RF002 y RF010)", body), still_live, len(rows)


def _build_conclusion(sql_live: int, sql_total: int, budget: _Budget) -> str:
    parts = [f"{budget.executed - budget.failed} consultas ejecutadas con éxito, {budget.failed} con error."]
    if sql_total:
        if sql_live:
            parts.append(
                f"{sql_live} de {sql_total} SQL del AWR siguen activas o entre las de mayor CPU: "
                "el problema del informe podría persistir; revisa su detalle con RF010."
            )
        else:
            parts.append(
                f"Ninguna de las {sql_total} SQL del AWR aparece ahora en vivo: "
                "el problema pudo ser puntual del periodo analizado."
            )
    return " ".join(parts)


def run_followup(analysis: AwrAnalysis) -> FollowupResult:
    """Ejecuta el seguimiento de solo lectura. Nunca lanza: los fallos se reflejan en el resultado."""
    try:
        get_connection()
    except Exception as exc:
        logger.warning("awr_followup_unavailable error=%s", type(exc).__name__)
        return FollowupResult(
            available=False,
            notes=["Contraste en vivo no disponible: sin conexión con la base de datos. Se muestra solo el análisis del informe."],
        )

    budget = _Budget()
    result = FollowupResult(available=True)
    sql_live = sql_total = 0

    if analysis.top_sql:
        try:
            section, sql_live, sql_total = _compare_top_sql(analysis, budget)
            result.sections.append(section)
        except Exception as exc:
            logger.warning("awr_followup_sql_compare_failed error=%s", type(exc).__name__)
            budget.executed += 1
            budget.failed += 1
            result.sections.append(
                FollowupSection("SQL del AWR frente al estado actual (RF002 y RF010)",
                                f"No se pudo ejecutar la consulta ({type(exc).__name__}).", ok=False)
            )

    areas = analysis.areas
    if not any(area.actions for area in areas) and not analysis.top_sql:
        areas = [GENERIC_FOLLOWUP]

    done: set[str] = set()
    for area in areas:
        outputs: list[str] = []
        ok = True
        for name in area.actions:
            if name in done or name not in ALLOWED_ACTIONS:
                continue
            if budget.exhausted():
                limit_note = "\nSe alcanzó el límite de tiempo o de consultas: seguimiento parcial."
                if limit_note not in result.notes:
                    result.notes.append(limit_note)
                break
            done.add(name)
            budget.executed += 1
            description = ALLOWED_ACTIONS[name][0]
            try:
                outputs.append(f"· {description}\n{_run_action(name)}")
            except Exception as exc:
                logger.warning("awr_followup_action_failed action=%s error=%s", name, type(exc).__name__)
                budget.failed += 1
                ok = False
                outputs.append(f"· {description}\nNo se pudo ejecutar ({type(exc).__name__}).")
        if outputs:
            result.sections.append(FollowupSection(f"{area.label} ({area.rf})", "\n".join(outputs), ok))

    result.conclusion = _build_conclusion(sql_live, sql_total, budget)
    return result


def analyze_with_followup(file_path: str | Path, followup: bool = True) -> AwrOutcome:
    """Resume el AWR y, si procede, ejecuta el seguimiento en vivo y lo añade al resultado."""
    analysis = parse_awr_report(file_path)
    summary = render_summary(analysis)
    if not followup:
        return AwrOutcome(summary)

    try:
        result = run_followup(analysis)
    except Exception as exc:  # defensa final: el resumen estático nunca debe perderse
        logger.error("awr_followup_error error=%s", type(exc).__name__)
        return AwrOutcome(summary, "Contraste en vivo no disponible por un error interno.")

    return AwrOutcome(summary, result.render_text())
