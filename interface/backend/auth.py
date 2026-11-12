"""
interface/backend/auth.py
Usuarios y roles de la web, sin tocar Oracle: los usuarios se guardan en un fichero JSON local
(data/users.json, contraseñas con hash PBKDF2) y las sesiones de login viven en memoria.

Roles (cada uno incluye los permisos del anterior):
- consulta:      ve el panel de estado, el histórico y usa el asistente.
- dba:           además fuerza revisiones nuevas, ve el detalle técnico y carga informes AWR.
- administrador: además gestiona usuarios.

Alta del primer administrador:
    python -m interface.backend.auth crear-usuario <usuario> --rol administrador
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROLES = ("consulta", "dba", "administrador")
_LEVEL = {role: i for i, role in enumerate(ROLES)}

DEFAULT_USERS_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "users.json"
PBKDF2_ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = 10
PASSPHRASE_LENGTH = 16  # a partir de esta longitud no se exige mezclar tipos de carácter
COMMON_PASSWORDS = frozenset({
    "password", "password1", "password123", "contrasena", "contraseña", "qwerty", "qwertyuiop", "123456789",
    "1234567890", "12345678910", "abc123456", "iloveyou", "admin1234", "administrador", "bienvenido",
    "bienvenido1", "oracle123", "oracle1234", "simba12345", "changeme", "letmein123", "passw0rd", "p@ssw0rd",
})
USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,40}$")

MAX_FAILED_LOGINS = 5
LOCKOUT_SECONDS = 300


class AuthError(Exception):
    """Error de validación con mensaje apto para el usuario."""


def has_role(role: str, required: str) -> bool:
    return _LEVEL.get(role, -1) >= _LEVEL[required]


def session_ttl_seconds() -> int:
    try:
        hours = float(os.environ.get("SIMBA_SESSION_HOURS", "8"))
    except ValueError:
        hours = 8.0
    return int(max(0.1, hours) * 3600)


def hash_password(password: str, iterations: int | None = None) -> str:
    iterations = iterations or PBKDF2_ITERATIONS
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), expected)


def password_problems(password: str, username: str = "") -> list[str]:
    """Motivos por los que una contraseña no cumple la política (lista vacía si es válida)."""
    password = password or ""
    problems = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"debe tener al menos {MIN_PASSWORD_LENGTH} caracteres")
    classes = sum(bool(re.search(rx, password)) for rx in (r"[a-z]", r"[A-Z]", r"\d", r"[^a-zA-Z0-9]"))
    if len(password) < PASSPHRASE_LENGTH and classes < 3:
        problems.append("debe combinar al menos 3 tipos de carácter (minúsculas, mayúsculas, números, símbolos) "
                        f"o tener {PASSPHRASE_LENGTH} caracteres o más")
    if username and len(username) >= 3 and username.lower() in password.lower():
        problems.append("no puede contener el nombre de usuario")
    if password.lower() in COMMON_PASSWORDS or len(set(password)) <= 2:
        problems.append("es demasiado común o predecible")
    return problems


def _validate_password(password: str, username: str = "") -> None:
    problems = password_problems(password, username)
    if problems:
        raise AuthError("La contraseña " + "; ".join(problems) + ".")


def _validate_role(role: str) -> None:
    if role not in ROLES:
        raise AuthError(f"Rol no válido. Opciones: {', '.join(ROLES)}.")


_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_hex(8))
    return _DUMMY_HASH


def _public(user: dict[str, Any]) -> dict[str, Any]:
    return {k: user.get(k) for k in ("username", "role", "active", "created_at")}


class UserStore:
    """Usuarios en un fichero JSON ({usuario: {...}}). Escritura atómica (fichero temporal + rename)."""

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path or os.environ.get("SIMBA_USERS_FILE", DEFAULT_USERS_FILE))
        self._lock = threading.Lock()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, users: dict[str, dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass

    def get(self, username: str) -> Optional[dict[str, Any]]:
        with self._lock:
            user = self._load().get(username)
        return dict(user) if user else None

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            users = self._load()
        return [_public(u) for u in sorted(users.values(), key=lambda u: u["username"])]

    def is_empty(self) -> bool:
        with self._lock:
            return not self._load()

    def authenticate(self, username: str, password: str) -> Optional[dict[str, Any]]:
        user = self.get(username)
        if not user or not user.get("active", True):
            # mismo coste que un login real para no revelar si el usuario existe
            verify_password(password, _dummy_hash())
            return None
        return _public(user) if verify_password(password, user["password_hash"]) else None

    def create(self, username: str, password: str, role: str) -> dict[str, Any]:
        if not USERNAME_RE.match(username or ""):
            raise AuthError("Usuario no válido: 3-40 caracteres (letras, números, punto, guion o guion bajo).")
        _validate_role(role)
        _validate_password(password, username)
        with self._lock:
            users = self._load()
            if username in users:
                raise AuthError("Ese usuario ya existe.")
            users[username] = {
                "username": username, "role": role, "active": True,
                "password_hash": hash_password(password),
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            self._save(users)
            return _public(users[username])

    def update(self, username: str, *, role: str | None = None, active: bool | None = None,
               password: str | None = None) -> dict[str, Any]:
        if role is not None:
            _validate_role(role)
        if password is not None:
            _validate_password(password, username)
        with self._lock:
            users = self._load()
            user = users.get(username)
            if not user:
                raise AuthError("Usuario no encontrado.")
            demotes_admin = user["role"] == "administrador" and (
                (role is not None and role != "administrador") or active is False)
            if demotes_admin and self._active_admins(users) <= 1:
                raise AuthError("Debe quedar al menos un administrador activo.")
            if role is not None:
                user["role"] = role
            if active is not None:
                user["active"] = bool(active)
            if password is not None:
                user["password_hash"] = hash_password(password)
            self._save(users)
            return _public(user)

    def delete(self, username: str) -> None:
        with self._lock:
            users = self._load()
            user = users.get(username)
            if not user:
                raise AuthError("Usuario no encontrado.")
            if user["role"] == "administrador" and user.get("active", True) and self._active_admins(users) <= 1:
                raise AuthError("Debe quedar al menos un administrador activo.")
            del users[username]
            self._save(users)

    @staticmethod
    def _active_admins(users: dict[str, dict[str, Any]]) -> int:
        return sum(1 for u in users.values() if u["role"] == "administrador" and u.get("active", True))


class SessionManager:
    """Tokens de login en memoria (se pierden al reiniciar el servidor) y bloqueo por intentos fallidos."""

    def __init__(self):
        self._sessions: dict[str, dict[str, Any]] = {}
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def create(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._purge()
            self._sessions[token] = {"username": username, "expires": time.time() + session_ttl_seconds(),
                                     "csrf": secrets.token_urlsafe(32)}
        return token

    def csrf_for(self, token: str | None) -> Optional[str]:
        """Token anti-CSRF ligado a la sesión (None si la sesión no existe o ha caducado)."""
        if not token:
            return None
        with self._lock:
            session = self._sessions.get(token)
            if not session or session["expires"] < time.time():
                return None
            return session["csrf"]

    def username_for(self, token: str | None) -> Optional[str]:
        if not token:
            return None
        with self._lock:
            session = self._sessions.get(token)
            if not session or session["expires"] < time.time():
                self._sessions.pop(token, None)
                return None
            return session["username"]

    def revoke(self, token: str | None) -> None:
        with self._lock:
            self._sessions.pop(token or "", None)

    def revoke_user(self, username: str) -> None:
        with self._lock:
            for token in [t for t, s in self._sessions.items() if s["username"] == username]:
                del self._sessions[token]

    def is_locked(self, username: str) -> bool:
        with self._lock:
            recent = [t for t in self._failures.get(username, []) if t > time.time() - LOCKOUT_SECONDS]
            self._failures[username] = recent
            return len(recent) >= MAX_FAILED_LOGINS

    def register_failure(self, username: str) -> None:
        with self._lock:
            self._failures.setdefault(username, []).append(time.time())

    def clear_failures(self, username: str) -> None:
        with self._lock:
            self._failures.pop(username, None)

    def _purge(self) -> None:
        now = time.time()
        for token in [t for t, s in self._sessions.items() if s["expires"] < now]:
            del self._sessions[token]


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Gestión de usuarios de la web de SIMBA.")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("crear-usuario", help="Crea un usuario (pide la contraseña por consola).")
    create.add_argument("username")
    create.add_argument("--rol", choices=ROLES, default="consulta")
    args = parser.parse_args()

    password = getpass.getpass("Contraseña: ")
    if password != getpass.getpass("Repite la contraseña: "):
        raise SystemExit("Las contraseñas no coinciden.")
    try:
        user = UserStore().create(args.username, password, args.rol)
    except AuthError as exc:
        raise SystemExit(str(exc))
    print(f"Usuario '{user['username']}' creado con rol '{user['role']}'.")


if __name__ == "__main__":
    _cli()
