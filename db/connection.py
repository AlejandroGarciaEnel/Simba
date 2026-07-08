"""
db/connection.py
Gestión del singleton de conexión Oracle.
Garantiza el cierre de la sesión ante cualquier tipo de salida del proceso.
"""
from __future__ import annotations

import atexit
import os
import signal
import sys
from typing import Optional

import cx_Oracle
from dotenv import load_dotenv

load_dotenv()
_oracle_client_dir = os.environ.get("ORACLE_CLIENT_DIR", r"C:\oracle\instantclient_23_0")
cx_Oracle.init_oracle_client(lib_dir=_oracle_client_dir)

_connection: Optional[cx_Oracle.Connection] = None


def get_connection() -> cx_Oracle.Connection:
    """Devuelve la conexión activa, creándola si no existe."""
    global _connection
    if _connection is None:
        _connection = _create_connection()
    return _connection


def _create_connection() -> cx_Oracle.Connection:
    host = os.environ["DB_HOST"]
    port = int(os.environ.get("DB_PORT", "1521"))
    service = os.environ["DB_SERVICE"]
    user = os.environ["DB_USER"]
    password = os.environ["DB_PASSWORD"]

    dsn = cx_Oracle.makedsn(host, port, service_name=service)
    conn = cx_Oracle.connect(user=user, password=password, dsn=dsn)
    # Modo solo lectura a nivel de transacción
    conn.autocommit = False
    return conn


def close_connection() -> None:
    """Cierra la conexión Oracle si está abierta."""
    global _connection
    if _connection is not None:
        try:
            _connection.close()
        except Exception:
            pass
        finally:
            _connection = None


def _signal_handler(sig: int, frame) -> None:  # noqa: ANN001
    close_connection()
    sys.exit(0)


# Garantizar cierre ante salida normal o señal
atexit.register(close_connection)
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)
