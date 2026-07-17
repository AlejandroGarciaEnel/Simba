"""
Servidor FastAPI que expone el agente Oracle a través de REST API.
Interfaz de comunicación entre frontend y agente LangChain.
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import logging
from typing import List, Dict, Any
from datetime import datetime

from .api_handlers import ChatHandler

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Inicializar FastAPI
app = FastAPI(
    title="SIMBA API",
    description="API para agente de monitorización Oracle",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Obtener rutas
BACKEND_DIR = Path(__file__).parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
PROJECT_ROOT = BACKEND_DIR.parent.parent

# Handler global
chat_handler = ChatHandler()
initialization_done = False


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
    message: str


# Endpoints
@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Verifica el estado del servidor y la conexión BD."""
    return {
        "status": "ok",
        "db_connected": chat_handler.db_connected,
        "message": "Servidor activo" if initialization_done else "Inicializando..."
    }


@app.post("/api/chat")
async def chat(payload: ChatMessage):
    """
    Endpoint principal de chat.
    Recibe pregunta del usuario y retorna respuesta del agente.
    """
    if not initialization_done or not chat_handler.executor:
        raise HTTPException(
            status_code=503,
            detail="El sistema no está inicializado. Verifica la conexión con la BD."
        )
    
    if not payload.message.strip():
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío.")
    
    try:
        # Procesar mensaje
        result = chat_handler.process_message(payload.message)
        
        # Si es solicitud de informe, generarlo
        if result.get("is_report"):
            success, filename, output_path = chat_handler.generate_report()
            if success:
                result["report"] = {
                    "success": True,
                    "filename": filename
                }
            else:
                result["report"] = {
                    "success": False,
                    "error": filename
                }
        
        return result
        
    except Exception as e:
        logger.error(f"Error en /api/chat: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reset-connection")
async def reset_connection():
    """
    Intenta resetear la conexión con la BD (3 reintentos).
    """
    try:
        success, message = chat_handler.reset_connection()
        return {
            "success": success,
            "message": message,
            "db_connected": chat_handler.db_connected
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
        
        file_path = PROJECT_ROOT / filename
        
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
async def get_chat_history():
    """Retorna el historial de chat actual."""
    return {
        "history": chat_handler.chat_history
    }


@app.post("/api/clear-history")
async def clear_history():
    """Limpia el historial de chat."""
    chat_handler.chat_history = []
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
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info"
    )
