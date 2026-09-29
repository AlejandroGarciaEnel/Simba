"""
Servidor FastAPI que expone el agente Oracle a través de REST API.
Interfaz de comunicación entre frontend y agente LangChain.
"""
import os
from fastapi import FastAPI, HTTPException, BackgroundTasks, Header, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import logging
from typing import List, Dict, Any
from datetime import datetime
from dotenv import load_dotenv

from .api_handlers import ChatHandler

load_dotenv()  # permite definir SIMBA_* en .env, igual que db/connection.py

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Inicializar FastAPI
app = FastAPI(
    title="SIMBA API",
    description="API para agente de monitorización Oracle",
    version="1.0.0"
)

def _get_cors_origins() -> List[str]:
    # riesgo aceptado: "*" solo mientras el uso sea local (ver docs/funtionalRequirements.md)
    raw = os.environ.get("SIMBA_CORS_ALLOWED_ORIGINS", "*").strip()
    if raw == "*":
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Session-Id"],
)

# Obtener rutas
BACKEND_DIR = Path(__file__).parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
PROJECT_ROOT = BACKEND_DIR.parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"

# Handler global (agente/conexión compartidos; el historial se aísla por sesión)
chat_handler = ChatHandler()
initialization_done = False

SESSION_HEADER = "X-Session-Id"


def resolve_session(response: Response, x_session_id: str | None = Header(default=None, alias=SESSION_HEADER)) -> str:
    """Resuelve el session id del request y lo propaga en la respuesta."""
    session_id = chat_handler.sessions.resolve(x_session_id)
    response.headers[SESSION_HEADER] = session_id
    return session_id


@app.on_event("startup")
async def startup_event():
    """Evento al iniciar servidor."""
    global initialization_done
    success, message = chat_handler.initialize_agent(max_retries=3)
    if success:
        logger.info(message)
        initialization_done = True
    else:
        logger.error(message)
    
    # Servir archivos estáticos del frontend
    try:
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    except Exception as e:
        logger.warning(f"No se pudieron montar archivos estáticos: {e}")


# Modelos
class ChatMessage(BaseModel):
    message: str
    history: List[Dict[str, str]] = []


class HealthResponse(BaseModel):
    status: str
    db_connected: bool
    llm_ready: bool
    db_error: str | None = None
    llm_error: str | None = None
    message: str


# Endpoints
@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Verifica el estado del servidor, la conexión a BD y el agente LLM por separado."""
    return {
        "status": "ok",
        "db_connected": chat_handler.db_connected,
        "llm_ready": chat_handler.llm_ready,
        "db_error": chat_handler.connection_error,
        "llm_error": chat_handler.llm_error,
        "message": "Servidor activo" if initialization_done else "Inicializando..."
    }


@app.post("/api/chat")
async def chat(payload: ChatMessage, response: Response, x_session_id: str | None = Header(default=None, alias=SESSION_HEADER)):
    """
    Endpoint principal de chat.
    Recibe pregunta del usuario y retorna respuesta del agente.
    """
    if not chat_handler.db_connected or not chat_handler.llm_ready or not chat_handler.executor:
        if chat_handler.db_connected and not chat_handler.llm_ready:
            detail = f"La base de datos está conectada, pero el agente (LLM) no pudo inicializarse: {chat_handler.llm_error}"
        elif not chat_handler.db_connected:
            detail = f"No hay conexión con la base de datos: {chat_handler.connection_error}"
        else:
            detail = "El sistema no está inicializado."
        raise HTTPException(status_code=503, detail=detail)
    
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío.")
    
    session_id = resolve_session(response, x_session_id)
    try:
        # Procesar mensaje dentro de la sesión aislada del cliente
        result = chat_handler.process_message(session_id, payload.message)
        
        return result
        
    except Exception as e:
        logger.error(f"Error en /api/chat: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reset-connection")
async def reset_connection():
    """
    Reintenta solo el/los componente(s) (BD y/o LLM) que estén fallando.
    """
    global initialization_done
    try:
        success, message = chat_handler.reset_connection()
        if success:
            initialization_done = True
        return {
            "success": success,
            "message": message,
            "db_connected": chat_handler.db_connected,
            "llm_ready": chat_handler.llm_ready
        }
    except Exception as e:
        logger.error(f"Error resetando conexión: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/download-report/{filename}")
async def download_report(filename: str):
    """
    Descarga un informe HTML generado.
    """
    try:
        # Validar nombre de archivo (seguridad)
        is_valid_prefix = filename.startswith("dbcheck_") or filename.startswith("dbCheck_")
        if not is_valid_prefix or not filename.endswith(".html"):
            raise HTTPException(status_code=400, detail="Nombre de archivo inválido.")
        
        file_path = REPORTS_DIR / filename
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Archivo no encontrado.")
        
        return FileResponse(
            path=file_path,
            media_type="text/html",
            filename=filename
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error descargando informe: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/chat-history")
async def get_chat_history(response: Response, x_session_id: str | None = Header(default=None, alias=SESSION_HEADER)):
    """Retorna el historial de chat de la sesión del cliente."""
    session_id = resolve_session(response, x_session_id)
    return {
        "history": chat_handler.sessions.get_history(session_id)
    }


@app.post("/api/clear-history")
async def clear_history(response: Response, x_session_id: str | None = Header(default=None, alias=SESSION_HEADER)):
    """Limpia el historial de chat de la sesión del cliente."""
    session_id = resolve_session(response, x_session_id)
    chat_handler.sessions.clear(session_id)
    return {
        "success": True,
        "message": "Historial limpiado"
    }


# Manejador de errores global
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Manejador global de excepciones."""
    logger.error(f"Error no manejado: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": f"Error interno del servidor: {str(exc)}",
            "error": True
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=os.environ.get("SIMBA_HOST", "127.0.0.1"),
        port=int(os.environ.get("SIMBA_PORT", "8000")),
        reload=True,
        log_level="info"
    )
