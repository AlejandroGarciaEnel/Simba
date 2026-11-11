"""
query_reports/board_store.py
Cambios hechos desde la web sobre el tablero de Queries (estado, prioridad, responsable y nota).

Se guardan aparte, en data/query_board.json, como capa local: los Excel del informe y del
seguimiento no se modifican nunca. Cada SQL_ID tiene como mucho un registro.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "query_board.json"
FIELDS = {"estado": 40, "prioridad": 20, "persona": 80, "nota": 4000}
COMMENT_MAX = 2000
COMMENTS_MAX = 200
SQL_ID_RE = re.compile(r"^[a-z0-9]{8,16}$")

_lock = threading.Lock()


def _path() -> Path:
    return Path(os.environ.get("SIMBA_QUERY_BOARD_FILE", DEFAULT_PATH))


def _load() -> dict[str, dict[str, Any]]:
    path = _path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict[str, dict[str, Any]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def normalize_sql_id(sql_id: str) -> str:
    sid = (sql_id or "").strip().lower()
    if not SQL_ID_RE.match(sid):
        raise ValueError("SQL_ID no válido.")
    return sid


def get_all() -> dict[str, dict[str, Any]]:
    with _lock:
        return _load()


def update(sql_id: str, changes: dict[str, Any], user: str) -> dict[str, Any] | None:
    """Aplica los campos recibidos (cadena vacía o null = quitar el cambio). Devuelve el registro o None si queda vacío."""
    sid = normalize_sql_id(sql_id)
    clean: dict[str, str | None] = {}
    for key, value in changes.items():
        if key not in FIELDS:
            raise ValueError(f"Campo no permitido: {key}")
        text = (value or "").strip() if isinstance(value, str) or value is None else None
        if text is None:
            raise ValueError(f"Valor no válido para {key}.")
        if len(text) > FIELDS[key]:
            raise ValueError(f"{key} supera {FIELDS[key]} caracteres.")
        clean[key] = text or None
    with _lock:
        data = _load()
        record = data.get(sid, {})
        for key, value in clean.items():
            if value is None:
                record.pop(key, None)
            else:
                record[key] = value
        if any(k in record for k in FIELDS):
            record["updated_by"] = user
            record["updated_at"] = _now()
        else:
            for key in ("updated_by", "updated_at"):
                record.pop(key, None)
        if record:
            data[sid] = record
        else:
            data.pop(sid, None)
            record = None
        _save(data)
    return record


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def add_comment(sql_id: str, text: str, user: str, role: str) -> dict[str, Any]:
    """Añade un comentario firmado (autor, rol y fecha) al hilo de la SQL."""
    sid = normalize_sql_id(sql_id)
    text = (text or "").strip()
    if not text:
        raise ValueError("El comentario está vacío.")
    if len(text) > COMMENT_MAX:
        raise ValueError(f"El comentario supera {COMMENT_MAX} caracteres.")
    with _lock:
        data = _load()
        record = data.setdefault(sid, {})
        comments = record.setdefault("comments", [])
        if len(comments) >= COMMENTS_MAX:
            raise ValueError("Se alcanzó el máximo de comentarios para esta SQL.")
        comment = {"id": uuid.uuid4().hex[:10], "author": user, "role": role, "at": _now(), "text": text}
        comments.append(comment)
        _save(data)
    return comment


def delete_comment(sql_id: str, comment_id: str, user: str, is_admin: bool) -> bool:
    """Borra un comentario; solo su autor o un administrador."""
    sid = normalize_sql_id(sql_id)
    with _lock:
        data = _load()
        record = data.get(sid, {})
        comments = record.get("comments", [])
        target = next((c for c in comments if c.get("id") == comment_id), None)
        if not target:
            return False
        if target.get("author") != user and not is_admin:
            raise PermissionError("Solo el autor o un administrador puede borrar el comentario.")
        record["comments"] = [c for c in comments if c is not target]
        if not record["comments"]:
            record.pop("comments")
        if record:
            data[sid] = record
        else:
            data.pop(sid, None)
        _save(data)
    return True


# ---- Notificaciones (campana) por usuario ----
NOTIF_MAX = 500
MENTION_RE = re.compile(r"@([A-Za-z0-9_.-]{2,40})")


def _notif_path() -> Path:
    return Path(os.environ.get("SIMBA_QUERY_NOTIF_FILE", _path().with_name("query_notifications.json")))


def _load_notifs() -> dict[str, Any]:
    try:
        data = json.loads(_notif_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"events": [], "seen": {}}
    if not isinstance(data, dict):
        return {"events": [], "seen": {}}
    data.setdefault("events", [])
    data.setdefault("seen", {})
    return data


def _save_notifs(data: dict[str, Any]) -> None:
    path = _notif_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _persona_matches(persona: str | None, username: str) -> bool:
    """Un responsable coincide con un usuario si es igual o contiene su nombre como palabra."""
    p, u = (persona or "").strip().lower(), username.lower()
    return bool(p) and (p == u or u in re.split(r"[^a-z0-9]+", p))


def recipients(sql_id: str, actor: str, known_users: list[str], text: str = "", extra_persona: str | None = None) -> list[str]:
    """Usuarios implicados en una SQL: responsable, autores de comentarios, quien la editó y @menciones."""
    sid = normalize_sql_id(sql_id)
    record = get_all().get(sid, {})
    involved = {c.get("author") for c in record.get("comments", [])} | {record.get("updated_by")}
    mentioned = {m.lower() for m in MENTION_RE.findall(text or "")}
    out = []
    for user in known_users:
        if user == actor:
            continue
        if (user in involved or user.lower() in mentioned
                or _persona_matches(record.get("persona"), user) or _persona_matches(extra_persona, user)):
            out.append(user)
    return out


def notify(sql_id: str, kind: str, by: str, text: str, to: list[str]) -> None:
    if not to:
        return
    with _lock:
        data = _load_notifs()
        data["events"].append({"id": uuid.uuid4().hex[:10], "sql_id": normalize_sql_id(sql_id), "kind": kind,
                               "by": by, "at": _now(), "text": (text or "")[:200], "to": to})
        data["events"] = data["events"][-NOTIF_MAX:]
        _save_notifs(data)


def notifications_for(user: str, limit: int = 30) -> dict[str, Any]:
    with _lock:
        data = _load_notifs()
    seen = data["seen"].get(user, "")
    mine = [e for e in data["events"] if user in e.get("to", [])]
    items = [{**{k: v for k, v in e.items() if k != "to"}, "unread": e["at"] > seen} for e in reversed(mine[-limit:])]
    return {"items": items, "unread": sum(1 for e in mine if e["at"] > seen)}


def mark_read(user: str) -> None:
    with _lock:
        data = _load_notifs()
        data["seen"][user] = _now()
        _save_notifs(data)
