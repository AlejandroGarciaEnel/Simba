"""
Vigilante de bloqueos: avisa por correo cuando una sesión bloquea a otras más de N segundos.

Solo consulta Oracle (SELECT). Está desactivado por defecto: se activa con SIMBA_ALERT_ENABLED=true y
necesita SIMBA_SMTP_HOST y SIMBA_ALERT_TO. Sin servidor de correo configurado no envía nada y solo avisa en el log.
"""
import asyncio
import logging
import os
import smtplib
import time
from email.message import EmailMessage
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def settings() -> Dict[str, Any]:
    return {
        "enabled": os.environ.get("SIMBA_ALERT_ENABLED", "").strip().lower() in ("1", "true", "yes", "si", "sí"),
        "threshold_s": _env_int("SIMBA_ALERT_BLOCK_S", 300),
        "interval_s": max(15, _env_int("SIMBA_ALERT_INTERVAL_S", 60)),
        "repeat_s": max(1, _env_int("SIMBA_ALERT_REPEAT_MIN", 30)) * 60,
        "host": os.environ.get("SIMBA_SMTP_HOST", "").strip(),
        "port": _env_int("SIMBA_SMTP_PORT", 587),
        "user": os.environ.get("SIMBA_SMTP_USER", "").strip(),
        "password": os.environ.get("SIMBA_SMTP_PASSWORD", ""),
        "starttls": os.environ.get("SIMBA_SMTP_STARTTLS", "true").strip().lower() not in ("0", "false", "no"),
        "sender": os.environ.get("SIMBA_ALERT_FROM", "").strip(),
        "to": [a.strip() for a in os.environ.get("SIMBA_ALERT_TO", "").split(",") if a.strip()],
    }


def blocker_key(r: Dict[str, Any]) -> str:
    return f"{r.get('instancia')}:{r.get('sid')},{r.get('serial')}"


def plan_alerts(roots: List[Dict[str, Any]], notified: Dict[str, float], now: float,
                threshold_s: int, repeat_s: int) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Decide qué avisar. `notified` (clave -> instante del último aviso) se modifica en el sitio.
    Devuelve (bloqueantes a avisar ahora, claves que ya se han liberado).
    """
    long_blockers = {blocker_key(r): r for r in roots if (r.get("segundos_espera") or 0) >= threshold_s}
    to_alert = []
    for key, r in long_blockers.items():
        if key not in notified or now - notified[key] >= repeat_s:
            notified[key] = now
            to_alert.append(r)
    released = [k for k in notified if k not in long_blockers]
    for k in released:
        del notified[k]
    return to_alert, released


def _mins(s: Any) -> str:
    return f"{round((s or 0) / 60, 1)} min"


def build_message(cfg: Dict[str, Any], alerts: List[Dict[str, Any]], released: List[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = cfg["sender"] or cfg["user"] or "simba@localhost"
    msg["To"] = ", ".join(cfg["to"])
    if alerts:
        msg["Subject"] = f"[SIMBA] Bloqueo de más de {cfg['threshold_s'] // 60} min ({len(alerts)} sesión/es)"
    else:
        msg["Subject"] = "[SIMBA] Bloqueo liberado"
    lines = []
    for r in alerts:
        lines += [
            f"Sesión bloqueante: inst {r.get('instancia')} · sid {r.get('sid')},{r.get('serial')}",
            f"  Usuario: {r.get('usuario') or '?'} ({r.get('usuario_so') or '?'}) · {r.get('maquina') or ''} · {r.get('programa') or ''}",
            f"  Bloquea a {r.get('sesiones_bloqueadas')} sesión/es · espera máxima {_mins(r.get('segundos_espera'))} · evento {r.get('evento') or '-'}",
            f"  Objeto: {r.get('objeto') or '-'}",
            f"  SQL {r.get('sql_id') or '-'} ({r.get('tipo_sql') or ''}): {r.get('sql_texto') or '-'}",
            "",
        ]
    if released:
        lines.append("Bloqueos liberados: " + ", ".join(released))
    lines += ["", "Aviso automático de SIMBA. Los datos son indicios: verifica antes de actuar."]
    msg.set_content("\n".join(lines))
    return msg


def send(cfg: Dict[str, Any], msg: EmailMessage) -> None:
    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as smtp:
        if cfg["starttls"]:
            smtp.starttls()
        if cfg["user"]:
            smtp.login(cfg["user"], cfg["password"])
        smtp.send_message(msg)


def tick(cfg: Dict[str, Any], notified: Dict[str, float], fetch_roots=None, sender=send) -> int:
    """Una pasada del vigilante. Devuelve el número de correos enviados."""
    if fetch_roots is None:
        from db import queries
        fetch_roots = lambda: [{k.lower(): v for k, v in r.items()} for r in queries.get_root_blockers(50)]
    roots = fetch_roots()
    to_alert, released = plan_alerts(roots, notified, time.monotonic(), cfg["threshold_s"], cfg["repeat_s"])
    if not to_alert and not released:
        return 0
    if not (cfg["host"] and cfg["to"]):
        logger.warning("Bloqueo > %s s detectado pero falta SIMBA_SMTP_HOST / SIMBA_ALERT_TO: no se envía correo.", cfg["threshold_s"])
        return 0
    try:
        sender(cfg, build_message(cfg, to_alert, released))
    except Exception:
        for r in to_alert:  # sin aviso entregado: se reintenta en el siguiente ciclo
            notified.pop(blocker_key(r), None)
        raise
    logger.info("Correo de bloqueos enviado (%d aviso/s, %d liberado/s)", len(to_alert), len(released))
    return 1


async def watch() -> None:
    """Bucle de fondo; los errores de Oracle o del correo nunca lo detienen."""
    cfg = settings()
    if not cfg["enabled"]:
        logger.info("Alertas de bloqueo por correo desactivadas (SIMBA_ALERT_ENABLED).")
        return
    logger.info("Alertas de bloqueo activas: umbral %s s, cada %s s", cfg["threshold_s"], cfg["interval_s"])
    notified: Dict[str, float] = {}
    while True:
        try:
            await asyncio.to_thread(tick, cfg, notified)
        except Exception:
            logger.exception("Fallo en el vigilante de bloqueos; se reintenta en el siguiente ciclo")
        await asyncio.sleep(cfg["interval_s"])
