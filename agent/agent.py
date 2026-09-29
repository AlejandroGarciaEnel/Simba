"""
agent/agent.py
Configura el agente LangChain con GPT-4o y las herramientas del monitor.
"""
from __future__ import annotations

import os

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
- Consultar el total de sesiones inactivas >30 min de un usuario específico (RF004.4)
- Listar las sesiones bloqueantes (RF005)
- Listar las SQLs de las sesiones bloqueantes (RF005.1)
- Consultar el total de SQLs de sesiones bloqueantes (RF005.2)
- Consultar el total de sesiones bloqueadas (RF005.3)
- Consultar un resumen general de la BBDD (RF007)
- Consultar métricas de rendimiento (RF008)
- Consultar detalle de SGA (RF008.1)
- Listar los usuarios con más sesiones activas (RF009)
- Listar el detalle de sesiones activas (RF009.1)
- Consultar el total de sesiones activas (RF009.2)
- Listar sesiones activas de un usuario específico (RF009.3)
- Consultar el total de sesiones activas de un usuario específico (RF009.4)
- Consultar información de SQL por SQL ID (RF010)
- Consultar sesiones por programa y máquina (RF011)
- Consultar sesiones por usuario (RF012)
- Consultar sesiones por módulo (RF013)
- Detectar patrones de pooling por umbral (RF014)
- Consultar métricas de latencia/waits (RF015)
- Consultar top de tamaño de tablas por esquema (RF016)
- Detectar bloqueos entre tablas (RF017)
- Consultar métricas de sesiones/usuarios por sysmetric (RF018)
- Consultar total de sesiones por usuario y estado (RF019)
- Consultar el total de sesiones conectadas, incluyendo cuántas están activas y cuántas llevan inactivas más de 30 minutos (RF020)
- Generar un informe HTML completo con la estructura funcional definida para el monitor (RF006)

Cuando el usuario no especifique cuántos resultados quiere, devuelve los 5 primeros por defecto.
Cuando una operación requiera parámetros obligatorios (por ejemplo username o sql_id), solicítalos si no están presentes.
Responde siempre en español.
Si no puedes resolver una petición con las herramientas disponibles, indícalo claramente.
"""


def build_agent():
    ssl_verify = os.environ.get("SSL_VERIFY", "true").lower() not in ("false", "0", "no")
    http_client = httpx.Client(verify=ssl_verify)

    provider = os.environ.get("LLM_PROVIDER", "openai").lower()

    if provider == "genaihub":
        token = _get_genaihub_token(http_client)
        model = _get_required_env("GENAIHUB_MODEL", "GENAI_MODEL_ID")
        base_url = _get_required_env("GENAIHUB_BASE_URL", "GENAIHUB_AWS_BASE_URL_DEV")
        api_key = token
        extra_body = {"modelId": model}
    else:
        model = os.environ.get("OPENAI_MODEL", "gpt-4o")
        base_url = os.environ.get("OPENAI_BASE_URL")
        api_key = os.environ["OPENAI_API_KEY"]
        extra_body = None

    llm = ChatOpenAI(
        model=model,
        temperature=0,
        api_key=api_key,
        base_url=base_url,
        http_client=http_client,
        extra_body=extra_body,
    )

    return create_agent(
        model=llm,
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
    )


def _get_required_env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip().strip('"')
    joined_names = ", ".join(names)
    raise RuntimeError(f"Falta configurar una de estas variables de entorno: {joined_names}")

def _get_genaihub_token(http_client: httpx.Client) -> str:
    tenant_id = _get_required_env("GENAIHUB_TENANT_ID")
    token_url = os.environ.get(
        "GENAIHUB_TOKEN_URL",
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
    )
    data = {
        "grant_type": "client_credentials",
        "client_id": _get_required_env("GENAIHUB_CLIENT_ID"),
        "client_secret": _get_required_env("GENAIHUB_CLIENT_SECRET"),
    }
    scope = os.environ.get("GENAIHUB_SCOPE")
    if not scope and "/oauth2/v2.0/token" in token_url:
        raise RuntimeError(
            "GENAIHUB_SCOPE es obligatorio para el endpoint OAuth v2.0 de GenAI Hub. "
            "Solicita al equipo de GenAI Hub el scope o audience correcto."
        )
    if scope:
        data["scope"] = scope

    response = http_client.post(
        token_url,
        data=data,
    )
    response.raise_for_status()
    return response.json()["access_token"]