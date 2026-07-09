"""
main.py
Punto de entrada del agente conversacional Monitor BBDD Oracle.
"""
from __future__ import annotations

import sys
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import AIMessage

load_dotenv()


BANNER = """
╔══════════════════════════════════════════════════════════╗
║          Monitor BBDD Oracle — Agente Simba              ║
╠══════════════════════════════════════════════════════════╣
║  Puedes preguntarme cosas como:                          ║
║  · ¿Cuánta CPU está usando la base de datos?             ║
║  · Dame las 10 queries que más CPU consumen              ║
║  · ¿Qué sesiones están bloqueando a otras?               ║
║  · Muéstrame los usuarios con más sesiones inactivas     ║
║  · Genera un informe HTML completo                       ║
║                                                          ║
║  Escribe 'salir' o pulsa Ctrl+C para terminar.           ║
╚══════════════════════════════════════════════════════════╝
"""


def _connect() -> bool:
    """Intenta conectar a la BBDD. Devuelve True si la conexión fue exitosa."""
    from db.connection import get_connection
    try:
        get_connection()
        return True
    except Exception as exc:
        print(f"  [ERROR] No se pudo conectar: {exc}")
        return False


def main() -> None:
    print(BANNER)

    # Intento 1
    print("Conectando a la base de datos...")
    if not _connect():
        print("Reintentando...")
        if not _connect():
            print("No se pudo establecer la conexión. Saliendo.")
            sys.exit(1)

    print("  Conexión establecida correctamente.\n")

    # Construir agente (importación tardía para no fallar antes de conectar)
    from agent.agent import build_agent
    executor = build_agent()

    chat_history: list[dict[str, str]] = []

    def _extract_answer(result: dict[str, Any]) -> str:
        """Obtiene el contenido final del asistente desde la salida del agente."""
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                content = msg.content
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts: list[str] = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                parts.append(text)
                    if parts:
                        return "\n".join(parts)
        return "[No se pudo extraer una respuesta del agente]"

    while True:
        try:
            user_input = input("Tú: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCerrando agente...")
            break

        if not user_input:
            continue

        if user_input.lower() in {"salir", "exit", "quit"}:
            print("Cerrando agente...")
            break

        try:
            chat_history.append({"role": "user", "content": user_input})
            result = executor.invoke({"messages": chat_history})
            answer = _extract_answer(result)
            chat_history.append({"role": "assistant", "content": answer})
        except Exception as exc:
            answer = f"[ERROR al procesar la consulta: {exc}]"

        print(f"\nSimba: {answer}\n")

    # El cierre de la conexión lo gestiona atexit en db/connection.py


if __name__ == "__main__":
    main()
