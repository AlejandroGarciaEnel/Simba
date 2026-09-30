"""
Adaptador que traduce mensajes del usuario a llamadas del agente LangChain.
Formatea respuestas para la API REST.
"""
import re
import secrets
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# Agregar raíz del proyecto al path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.agent import build_agent
from db.connection import get_connection
from langchain_core.messages import AIMessage

# Formato esperado de un session id emitido por secrets.token_urlsafe(32)
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
SESSION_TTL = timedelta(minutes=30)
MAX_HISTORY_MESSAGES = 200
MAX_CONCURRENT_SESSIONS = 500


class SessionStore:
    """Historiales de chat aislados por sesión, con expiración por inactividad."""

    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def resolve(self, requested_id: Optional[str]) -> str:
        """
        Devuelve un session id válido y activo. El servidor es la única autoridad
        que emite ids: si el propuesto no es válido/activo, se crea uno nuevo.
        """
        with self._lock:
            self._purge_expired()
            if requested_id and self._is_active(requested_id):
                self._touch(requested_id)
                return requested_id
            return self._create()

    def get_history(self, session_id: str) -> List[Dict]:
        with self._lock:
            session = self._sessions.get(session_id)
            return list(session["history"]) if session else []

    def append_message(self, session_id: str, role: str, content: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            session["history"].append({"role": role, "content": content})
            # limitar crecimiento del historial por sesión (ver docs/funtionalRequirements.md)
            session["history"] = session["history"][-MAX_HISTORY_MESSAGES:]
            self._touch(session_id)
            return True

    def clear(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id]["history"] = []
                self._touch(session_id)

    def _is_active(self, session_id: str) -> bool:
        if not _SESSION_ID_PATTERN.match(session_id):
            return False
        session = self._sessions.get(session_id)
        return session is not None and not self._is_expired(session)

    def _is_expired(self, session: Dict[str, Any]) -> bool:
        return datetime.utcnow() - session["last_activity"] > SESSION_TTL

    def _touch(self, session_id: str) -> None:
        self._sessions[session_id]["last_activity"] = datetime.utcnow()

    def _purge_expired(self) -> None:
        expired = [sid for sid, s in self._sessions.items() if self._is_expired(s)]
        for sid in expired:
            del self._sessions[sid]
        self._evict_oldest_if_over_capacity()

    def _evict_oldest_if_over_capacity(self) -> None:
        # protección DoS: limita sesiones concurrentes descartando la más antigua (LRU)
        while len(self._sessions) > MAX_CONCURRENT_SESSIONS:
            oldest_id = min(self._sessions, key=lambda sid: self._sessions[sid]["last_activity"])
            del self._sessions[oldest_id]

    def _create(self) -> str:
        session_id = secrets.token_urlsafe(32)
        self._sessions[session_id] = {"history": [], "last_activity": datetime.utcnow()}
        self._evict_oldest_if_over_capacity()
        return session_id


class ChatHandler:
    """Manejador de chat que integra el agente Oracle con la API REST."""
    
    def __init__(self):
        self.executor = None
        self.sessions = SessionStore()
        self.db_connected = False
        self.connection_error = None
        self.llm_ready = False
        self.llm_error = None

    def _connect_database(self, max_retries: int = 3) -> Tuple[bool, str]:
        """Gestiona solo la conexión Oracle con reintentos. No toca el estado del LLM."""
        for attempt in range(max_retries):
            try:
                get_connection()
                self.db_connected = True
                self.connection_error = None
                return True, "Conexión con la base de datos establecida correctamente."
            except Exception as e:
                self.connection_error = str(e)
                if attempt < max_retries - 1:
                    continue
        self.db_connected = False
        return False, (
            f"No se pudo establecer conexión con la base de datos después de {max_retries} intentos."
        )

    def _build_llm_agent(self) -> Tuple[bool, str]:
        """Gestiona solo la construcción del agente LLM. No toca el estado de la BD."""
        try:
            self.executor = build_agent()
            self.llm_ready = True
            self.llm_error = None
            return True, "Agente LLM inicializado correctamente."
        except Exception as e:
            self.executor = None
            self.llm_ready = False
            self.llm_error = str(e)
            return False, f"Error al inicializar el agente LLM: {e}"

    def initialize_agent(self, max_retries: int = 3) -> Tuple[bool, str]:
        """
        Inicializa BD y agente LLM como pasos independientes: un fallo del LLM
        no debe pisar el estado (ya correcto) de la conexión a BD, y viceversa.
        
        Args:
            max_retries: Número máximo de intentos de conexión a BD
            
        Returns:
            (éxito: bool, mensaje: str)
        """
        db_ok, db_message = self._connect_database(max_retries)
        if not db_ok:
            return False, db_message

        llm_ok, llm_message = self._build_llm_agent()
        if not llm_ok:
            return False, f"Base de datos conectada, pero {llm_message}"

        return True, "Conexión establecida correctamente. ¿Qué deseas saber de la base de datos?"

    def _extract_answer(self, result: Dict[str, Any]) -> str:
        """
        Extrae la respuesta del asistente desde la salida del agente.
        Mismo patrón que en main.py
        """
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                content = msg.content
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts: List[str] = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                parts.append(text)
                    if parts:
                        return "\n".join(parts)
        return "No se pudo extraer una respuesta del agente"
    
    def process_message(self, session_id: str, user_message: str) -> Dict[str, Any]:
        """
        Procesa un mensaje del usuario y obtiene respuesta del agente.
        
        Args:
            session_id: Identificador de la sesión aislada del cliente
            user_message: Mensaje del usuario
            
        Returns:
            Dict con respuesta formateada para frontend
        """
        if not self.executor:
            return {
                "success": False,
                "message": "El agente no está inicializado.",
                "error": True,
                "can_retry": True
            }
        
        # Agregar mensaje del usuario al historial de la sesión
        if not self.sessions.append_message(session_id, "user", user_message):
            return {
                "success": False,
                "message": "Tu sesión expiró por inactividad. Se ha iniciado una nueva sesión, por favor reenvía tu pregunta.",
                "error": True,
                "can_retry": True
            }
        
        try:
            # Invocar agente con historial de la sesión
            history = self.sessions.get_history(session_id)
            result = self.executor.invoke({"messages": history})
            
            # Extraer respuesta
            assistant_message = self._extract_answer(result)
            
            # Agregar respuesta al historial de la sesión
            self.sessions.append_message(session_id, "assistant", assistant_message)

            report_filename = self._extract_generated_filename(assistant_message, "dbCheck")            
            return {
                "success": True,
                "message": assistant_message,
                "error": False,
                "is_report": bool(report_filename),
                "report": {"success": True, "filename": report_filename} if report_filename else None,
                "can_retry": False
            }
            
        except Exception as e:
            error_msg = str(e)
            
            # Verificar si es error de conexión BD
            if "database" in error_msg.lower() or "connection" in error_msg.lower():
                return {
                    "success": False,
                    "message": f"Error de conexión con la base de datos: {error_msg}. Por favor, utiliza el botón de reintentar.",
                    "error": True,
                    "can_retry": True,
                    "is_bd_error": True
                }
            
            return {
                "success": False,
                "message": f"Error procesando tu pregunta: {error_msg}",
                "error": True,
                "can_retry": False
            }
    
    def _extract_generated_filename(self, message: str, prefix: str) -> str | None:
        pattern = rf"\b{re.escape(prefix)}[^\s]*\.html\b"
        match = re.search(pattern, message or "")
        if not match:
            return None
        return Path(match.group(0)).name
    
    def generate_report(self) -> Tuple[bool, str, str]:
        """
        Genera un informe HTML.
        
        Returns:
            (éxito: bool, filename: str, ruta_completa: str)
        """
        try:
            from report.generator import generate
            from pathlib import Path
            
            # generate() ya guarda en disco y retorna la ruta completa
            output_path = generate()
            
            # Extraer solo el filename
            filename = Path(output_path).name
            
            return True, filename, output_path
            
        except Exception as e:
            return False, "", str(e)
    
    def reset_connection(self) -> Tuple[bool, str]:
        """
        Reintenta solo el/los componente(s) que estén fallando: si la BD ya está
        conectada, no la reintenta y solo reconstruye el agente LLM (y viceversa).
        """
        if not self.db_connected:
            return self.initialize_agent(max_retries=3)
        if not self.llm_ready:
            llm_ok, llm_message = self._build_llm_agent()
            if not llm_ok:
                return False, llm_message
            return True, "Conexión establecida correctamente. ¿Qué deseas saber de la base de datos?"
        return True, "El sistema ya está operativo."
