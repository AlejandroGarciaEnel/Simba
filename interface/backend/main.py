"""
Servidor FastAPI que expone el agente Oracle a través de REST API.
Interfaz de comunicación entre frontend y agente LangChain.
"""
import asyncio
import os
from fastapi import FastAPI, HTTPException, BackgroundTasks, Header, Response, UploadFile, File, Request, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import logging
from typing import List, Dict, Any
from datetime import datetime
from dotenv import load_dotenv

from .api_handlers import ChatHandler, AwrUploadError, awr_max_bytes
from .auth import AuthError, SessionManager, UserStore, has_role, session_ttl_seconds

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

AWR_UPLOAD_PATH = "/api/awr/upload"


@app.middleware("http")
async def limit_awr_upload_size(request, call_next):
    # se rechaza antes de que Starlette vuelque el multipart a disco (64 KB de margen para cabeceras)
    if request.url.path == AWR_UPLOAD_PATH:
        content_length = request.headers.get("content-length", "")
        if content_length.isdigit() and int(content_length) > awr_max_bytes() + 64 * 1024:
            return JSONResponse(status_code=413, content={"detail": "El informe AWR supera el tamaño máximo permitido."})
    return await call_next(request)

# Obtener rutas
BACKEND_DIR = Path(__file__).parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
PROJECT_ROOT = BACKEND_DIR.parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"

# Handler global (agente/conexión compartidos; el historial se aísla por sesión)
chat_handler = ChatHandler()
initialization_done = False

SESSION_HEADER = "X-Session-Id"

# ── Usuarios y roles ─────────────────────────────────────────────────────────
AUTH_COOKIE = "simba_session"
user_store = UserStore()
login_sessions = SessionManager()


def current_user(request: Request) -> Dict[str, str]:
    """Usuario de la cookie de sesión; se relee del fichero para que un cambio de rol o una baja apliquen ya."""
    username = login_sessions.username_for(request.cookies.get(AUTH_COOKIE))
    user = user_store.get(username) if username else None
    if not user or not user.get("active", True):
        raise HTTPException(status_code=401, detail="Sesión no iniciada o caducada.")
    return {"username": user["username"], "role": user["role"]}


def require_role(role: str):
    def dependency(user: Dict[str, str] = Depends(current_user)) -> Dict[str, str]:
        if not has_role(user["role"], role):
            raise HTTPException(status_code=403, detail="No tienes permisos para esta acción.")
        return user
    return dependency


as_consulta = require_role("consulta")
as_dba = require_role("dba")
as_admin = require_role("administrador")


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

    if user_store.is_empty():
        logger.warning("No hay usuarios en la web. Crea el primer administrador con: "
                       "python -m interface.backend.auth crear-usuario <usuario> --rol administrador")
    
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


class LoginRequest(BaseModel):
    username: str
    password: str


class NewUser(BaseModel):
    username: str
    password: str
    role: str = "consulta"


class UserUpdate(BaseModel):
    role: str | None = None
    active: bool | None = None
    password: str | None = None


def _cookie_secure() -> bool:
    return os.environ.get("SIMBA_COOKIE_SECURE", "false").strip().lower() in ("1", "true", "yes")


# Autenticación
@app.post("/api/auth/login")
async def login(payload: LoginRequest, response: Response):
    username = payload.username.strip()
    if login_sessions.is_locked(username):
        raise HTTPException(status_code=429, detail="Demasiados intentos fallidos. Espera unos minutos.")
    user = await run_in_threadpool(user_store.authenticate, username, payload.password)
    if not user:
        login_sessions.register_failure(username)
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")
    login_sessions.clear_failures(username)
    token = login_sessions.create(user["username"])
    response.set_cookie(AUTH_COOKIE, token, max_age=session_ttl_seconds(), httponly=True,
                        samesite="strict", secure=_cookie_secure())
    logger.info("login user=%s role=%s", user["username"], user["role"])
    return {"username": user["username"], "role": user["role"]}


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    login_sessions.revoke(request.cookies.get(AUTH_COOKIE))
    response.delete_cookie(AUTH_COOKIE)
    return {"success": True}


@app.get("/api/auth/me")
async def me(user: Dict[str, str] = Depends(current_user)):
    return user


# Gestión de usuarios (administrador)
@app.get("/api/users")
async def list_users(_: Dict[str, str] = Depends(as_admin)):
    return {"users": user_store.list()}


@app.post("/api/users", status_code=201)
async def create_user(payload: NewUser, admin: Dict[str, str] = Depends(as_admin)):
    try:
        user = await run_in_threadpool(user_store.create, payload.username.strip(), payload.password, payload.role)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    logger.info("user_created by=%s user=%s role=%s", admin["username"], user["username"], user["role"])
    return user


@app.patch("/api/users/{username}")
async def update_user(username: str, payload: UserUpdate, admin: Dict[str, str] = Depends(as_admin)):
    try:
        user = await run_in_threadpool(
            lambda: user_store.update(username, role=payload.role, active=payload.active, password=payload.password))
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if payload.active is False or payload.password is not None:
        login_sessions.revoke_user(username)
    logger.info("user_updated by=%s user=%s", admin["username"], username)
    return user


@app.delete("/api/users/{username}")
async def delete_user(username: str, admin: Dict[str, str] = Depends(as_admin)):
    if username == admin["username"]:
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propio usuario.")
    try:
        user_store.delete(username)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    login_sessions.revoke_user(username)
    logger.info("user_deleted by=%s user=%s", admin["username"], username)
    return {"success": True}


# Endpoints
@app.get("/api/health", response_model=HealthResponse)
async def health_check(_: Dict[str, str] = Depends(as_consulta)):
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
async def chat(payload: ChatMessage, response: Response, x_session_id: str | None = Header(default=None, alias=SESSION_HEADER),
               user: Dict[str, str] = Depends(as_consulta)):
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
        # Procesar mensaje dentro de la sesión aislada del cliente; si el agente revisa el estado,
        # queda registrado a nombre del usuario y solo un DBA puede forzar una revisión nueva.
        from health.checker import CAN_FORCE_REFRESH, REQUESTER

        REQUESTER.set(user["username"])
        CAN_FORCE_REFRESH.set(has_role(user["role"], "dba"))
        result = chat_handler.process_message(session_id, payload.message)
        
        return result
        
    except Exception as e:
        logger.error(f"Error en /api/chat: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reset-connection")
async def reset_connection(_: Dict[str, str] = Depends(as_dba)):
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
async def download_report(filename: str, _: Dict[str, str] = Depends(as_consulta)):
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


@app.post(AWR_UPLOAD_PATH)
async def upload_awr(
    response: Response,
    file: UploadFile = File(...),
    x_session_id: str | None = Header(default=None, alias=SESSION_HEADER),
    _: Dict[str, str] = Depends(as_dba),
):
    """Recibe un informe AWR (RF021), lo guarda en awr/ y devuelve su resumen. No requiere BD ni LLM."""
    session_id = resolve_session(response, x_session_id)
    session_headers = {SESSION_HEADER: session_id}
    max_bytes = awr_max_bytes()
    chunks: List[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413, detail="El informe AWR supera el tamaño máximo permitido.", headers=session_headers
            )
        chunks.append(chunk)

    try:
        return await run_in_threadpool(
            chat_handler.store_and_analyze_awr, session_id, file.filename or "", b"".join(chunks)
        )
    except AwrUploadError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e), headers=session_headers)
    except Exception as e:
        logger.error(f"Error analizando informe AWR: {str(e)}")
        raise HTTPException(status_code=500, detail="No se pudo analizar el informe AWR.", headers=session_headers)

@app.get("/api/chat-history")
async def get_chat_history(response: Response, x_session_id: str | None = Header(default=None, alias=SESSION_HEADER),
                           _: Dict[str, str] = Depends(as_consulta)):
    """Retorna el historial de chat de la sesión del cliente."""
    session_id = resolve_session(response, x_session_id)
    return {
        "history": chat_handler.sessions.get_history(session_id)
    }


@app.post("/api/clear-history")
async def clear_history(response: Response, x_session_id: str | None = Header(default=None, alias=SESSION_HEADER),
                        _: Dict[str, str] = Depends(as_consulta)):
    """Limpia el historial de chat de la sesión del cliente."""
    session_id = resolve_session(response, x_session_id)
    chat_handler.sessions.clear(session_id)
    return {
        "success": True,
        "message": "Historial limpiado"
    }


@app.get("/inactivas", include_in_schema=False)
async def inactive_sessions_page():
    """Página con el listado completo de sesiones inactivas (la API exige rol dba)."""
    return FileResponse(FRONTEND_DIR / "inactivas.html")


_inactive_cache: Dict[str, Any] = {"at": 0.0, "rows": []}
INACTIVE_LIST_TTL_S = 60


@app.get("/api/inactive-sessions")
async def inactive_sessions(_: Dict[str, str] = Depends(as_dba)):
    """Listado de sesiones inactivas > 30 min (solo SELECT; caché de 60 s para no cargar Oracle)."""
    import time

    from db import queries

    if time.monotonic() - _inactive_cache["at"] > INACTIVE_LIST_TTL_S:
        try:
            raw = await run_in_threadpool(queries.get_cluster_inactive_session_list)
            rows = [{k.lower(): v for k, v in r.items()} for r in raw]
        except Exception:
            logger.exception("Error al listar sesiones inactivas")
            raise HTTPException(status_code=500, detail="No se pudo obtener el listado de sesiones inactivas.")
        _inactive_cache.update(at=time.monotonic(), rows=rows, taken=datetime.now().isoformat(timespec="seconds"))
    return {"sessions": _inactive_cache["rows"], "taken_at": _inactive_cache.get("taken"), "total": len(_inactive_cache["rows"])}


_blocking_cache: Dict[str, Any] = {"at": 0.0}
_blocking_lock = asyncio.Lock()
BLOCKING_TTL_S = 15


@app.get("/api/blocking-sessions")
async def blocking_sessions(_: Dict[str, str] = Depends(as_dba)):
    """Sesiones bloqueantes (raíz) y las sesiones que bloquea cada una (solo SELECT; caché de 15 s)."""
    import time

    from db import queries

    def work():
        roots = queries.get_root_blockers(50)
        waiting = queries.get_blocked_session_list()
        names = queries.get_object_names([w.get("OBJ_ID") for w in waiting])
        texts = queries.get_sql_texts([w.get("SQL_ID") for w in waiting])
        for w in waiting:
            w["SQL_TEXTO"] = texts.get(w.get("SQL_ID"))
            w["OBJETO"] = names.get(int(w["OBJ_ID"])) if w.get("OBJ_ID") else None
        return ([{k.lower(): v for k, v in r.items()} for r in roots],
                [{k.lower(): v for k, v in r.items()} for r in waiting])

    # El lock evita que varias pestañas lancen la misma consulta a la vez.
    async with _blocking_lock:
        if time.monotonic() - _blocking_cache["at"] > BLOCKING_TTL_S:
            try:
                roots, waiting = await run_in_threadpool(work)
            except Exception:
                logger.exception("Error al listar sesiones bloqueantes")
                raise HTTPException(status_code=500, detail="No se pudo obtener el detalle de bloqueos.")
            _blocking_cache.update(at=time.monotonic(), roots=roots, waiting=waiting,
                                   taken=datetime.now().isoformat(timespec="seconds"))
    return {"roots": _blocking_cache["roots"], "waiting": _blocking_cache["waiting"], "taken_at": _blocking_cache.get("taken")}


@app.get("/api/query-improvements")
async def query_improvements(_: Dict[str, str] = Depends(as_consulta)):
    """Recomendaciones sobre el informe semanal de queries y su seguimiento (lectura de Excel, sin LLM)."""
    from query_reports.advisor import get_query_improvements

    return await run_in_threadpool(get_query_improvements)


@app.get("/api/query-board")
async def query_board_overrides(_: Dict[str, str] = Depends(as_consulta)):
    """Cambios locales del tablero de Queries (estado, prioridad, responsable, nota)."""
    from query_reports import board_store

    return {"overrides": await run_in_threadpool(board_store.get_all)}


class QueryBoardUpdate(BaseModel):
    estado: str | None = None
    prioridad: str | None = None
    persona: str | None = None
    nota: str | None = None


@app.put("/api/query-board/{sql_id}")
async def query_board_update(sql_id: str, body: QueryBoardUpdate, user: Dict[str, str] = Depends(as_dba)):
    """Mueve una SQL de columna o edita sus datos. No toca los Excel; solo guarda una capa local."""
    from query_reports import board_store
    from query_reports.advisor import get_query_improvements

    changes = body.model_dump(exclude_unset=True)
    try:
        if changes.get("estado"):
            states = (await run_in_threadpool(get_query_improvements)).get("states") or []
            if changes["estado"] not in states:
                raise ValueError("Estado no válido.")
        record = await run_in_threadpool(board_store.update, sql_id, changes, user["username"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"sql_id": sql_id.strip().lower(), "override": record}


class QueryCommentIn(BaseModel):
    text: str


@app.post("/api/query-board/{sql_id}/comments")
async def query_board_add_comment(sql_id: str, body: QueryCommentIn, user: Dict[str, str] = Depends(as_dba)):
    """Añade un comentario al hilo de una SQL, firmado con el usuario y su rol."""
    from query_reports import board_store

    try:
        comment = await run_in_threadpool(board_store.add_comment, sql_id, body.text, user["username"], user["role"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"comment": comment}


@app.delete("/api/query-board/{sql_id}/comments/{comment_id}")
async def query_board_delete_comment(sql_id: str, comment_id: str, user: Dict[str, str] = Depends(as_dba)):
    from query_reports import board_store

    try:
        ok = await run_in_threadpool(
            board_store.delete_comment, sql_id, comment_id, user["username"], user["role"] == "administrador")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    if not ok:
        raise HTTPException(status_code=404, detail="Comentario no encontrado.")
    return {"ok": True}


@app.get("/api/sql-analysis/{sql_id}")
async def sql_analysis(sql_id: str, force: bool = False, _: Dict[str, str] = Depends(as_dba)):
    """Análisis de una SQL problemática (planes, AWR, estadísticas, índices). Solo DBA; solo SELECT."""
    from query_reports.advisor import get_query_improvements
    from query_reports.sql_analysis import analyze_sql

    def work():
        board = get_query_improvements().get("board") or []
        context = next((c for c in board if c["sql_id"] == sql_id.strip().lower()), None)
        return analyze_sql(sql_id, context=context, force=force)

    try:
        return await run_in_threadpool(work)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/health-history")
async def health_history(limit: int = 20, _: Dict[str, str] = Depends(as_consulta)):
    """Histórico de preguntas sobre el estado de la BBDD y lo que se devolvió en cada una."""
    from health.store import HealthStore

    return {"history": await run_in_threadpool(HealthStore().history, limit)}


@app.post("/api/health-check")
async def health_check_now(
    response: Response,
    force: bool = False,
    x_session_id: str | None = Header(default=None, alias=SESSION_HEADER),
    user: Dict[str, str] = Depends(as_consulta),
):
    """Revisión de estado (reutiliza la caché si no ha caducado; force=true la ignora, solo DBA)."""
    from health.checker import get_health

    if force and not has_role(user["role"], "dba"):
        raise HTTPException(status_code=403, detail="Solo un DBA puede forzar una revisión nueva.")
    resolve_session(response, x_session_id)
    try:
        return await run_in_threadpool(get_health, user["username"], force)
    except Exception:
        logger.exception("Error en la revisión de estado")
        raise HTTPException(status_code=500, detail="No se pudo realizar la revisión de estado.")


@app.get("/api/health-check/{check_id}/detail")
async def health_check_detail(check_id: int, _: Dict[str, str] = Depends(as_dba)):
    """Datos técnicos de cada comprobación de una revisión (solo DBA)."""
    from health.store import HealthStore

    check = await run_in_threadpool(HealthStore().get_check, check_id)
    if not check:
        raise HTTPException(status_code=404, detail="Revisión no encontrada.")
    return {"id": check["id"], "created_at": check["created_at"], "raw": check.get("raw", {})}


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
