"""
agent/agent.py
Configura el agente LangChain con GPT-4o y las herramientas del monitor.
"""
from __future__ import annotations

import os
import ssl

import httpx
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from agent.tools import ALL_TOOLS

load_dotenv()

SYSTEM_PROMPT = """Eres un agente experto en monitorización de bases de datos Oracle.
Tu función es ayudar al administrador a conocer el estado de rendimiento de la base de datos
respondiendo sus preguntas en lenguaje natural.

Puedes ejecutar las siguientes acciones:
- Consultar el porcentaje de CPU actual de la base de datos (RF001)
- Listar las queries que más CPU consumen (RF002)
- Listar las sesiones que más CPU consumen (RF003)
- Listar los usuarios con más sesiones inactivas >30 min (RF004)
- Listar el detalle de sesiones inactivas/huérfanas >30 min (RF004.1)
- Consultar el total de sesiones inactivas/huérfanas >30 min (RF004.2)
- Listar sesiones inactivas >30 min de un usuario específico (RF004.3)
- Listar las sesiones bloqueantes (RF005)
- Listar las SQLs de las sesiones bloqueantes (RF005.1)
- Consultar el total de SQLs de sesiones bloqueantes (RF005.2)
- Consultar el total de sesiones bloqueadas (RF005.3)
- Generar un informe HTML completo con toda la información anterior (RF006)

Cuando el usuario no especifique cuántos resultados quiere, devuelve los 5 primeros por defecto.
Responde siempre en español.
Si no puedes resolver una petición con las herramientas disponibles, indícalo claramente.
"""


def build_agent():
    model = os.environ.get("OPENAI_MODEL", "gpt-4o")

    # Entornos corporativos con proxy SSL autofirmado requieren deshabilitar
    # la verificación de certificados. Controlado por SSL_VERIFY en .env.
    ssl_verify = os.environ.get("SSL_VERIFY", "true").lower() not in ("false", "0", "no")
    http_client = httpx.Client(verify=ssl_verify)

    llm = ChatOpenAI(
        model=model,
        temperature=0,
        base_url=os.environ.get("OPENAI_BASE_URL"),
        http_client=http_client,
    )

    return create_agent(
        model=llm,
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
    )
