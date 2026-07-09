"""
Adaptador que traduce mensajes del usuario a llamadas del agente LangChain.
Formatea respuestas para la API REST.
"""
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Any
import json
from datetime import datetime

# Agregar raíz del proyecto al path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.agent import build_agent
from db.connection import get_connection
from langchain_core.messages import AIMessage


class ChatHandler:
    """Manejador de chat que integra el agente Oracle con la API REST."""
    
    def __init__(self):
        self.executor = None
        self.chat_history: List[Dict] = []
        self.db_connected = False
        self.connection_error = None
    
    def initialize_agent(self, max_retries: int = 3) -> Tuple[bool, str]:
        """
        Inicializa el agente y verifica conexión a BD.
        
        Args:
            max_retries: Número máximo de intentos de conexión
            
        Returns:
            (éxito: bool, mensaje: str)
        """
        try:
            # Intentar conexión a BD
            for attempt in range(max_retries):
                try:
                    get_connection()
                    self.db_connected = True
                    self.connection_error = None
                    break
                except Exception as e:
                    self.connection_error = str(e)
                    if attempt < max_retries - 1:
                        continue
                    else:
                        raise
            
            if not self.db_connected:
                return False, "No se pudo establecer conexión con la base de datos después de 3 intentos."
            
            # Construir agente
            self.executor = build_agent()
            return True, "Conexión establecida correctamente. ¿Qué deseas saber de la base de datos?"
            
        except Exception as e:
            self.db_connected = False
            self.connection_error = str(e)
            return False, f"Error al inicializar el sistema: {str(e)}"
    
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
    
    def process_message(self, user_message: str) -> Dict[str, Any]:
        """
        Procesa un mensaje del usuario y obtiene respuesta del agente.
        
        Args:
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
        
        # Agregar mensaje del usuario al historial
        self.chat_history.append({
            "role": "user",
            "content": user_message
        })
        
        try:
            # Invocar agente con historial (igual que en main.py)
            result = self.executor.invoke({"messages": self.chat_history})
            
            # Extraer respuesta
            assistant_message = self._extract_answer(result)
            
            # Agregar respuesta al historial
            self.chat_history.append({
                "role": "assistant",
                "content": assistant_message
            })
            
            # Detectar si es solicitud de informe
            is_report_request = self._is_report_request(user_message)
            
            return {
                "success": True,
                "message": assistant_message,
                "error": False,
                "is_report": is_report_request,
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
    
    def _is_report_request(self, user_msg: str) -> bool:
        """
        Detecta si la solicitud es para generar un informe.
        """
        keywords = ["informe", "reporte", "report", "generar", "genera", "crear", "html"]
        user_lower = user_msg.lower()
        return any(keyword in user_lower for keyword in keywords)
    
    def generate_report(self) -> Tuple[bool, bytes, str]:
        """
        Genera un informe HTML.
        
        Returns:
            (éxito: bool, contenido_bytes: bytes, nombre_archivo: str)
        """
        try:
            from report.generator import ReportGenerator
            
            generator = ReportGenerator()
            html_content = generator.generate()
            
            filename = f"dbcheck_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
            
            return True, html_content.encode('utf-8'), filename
            
        except Exception as e:
            return False, b"", str(e)
    
    def reset_connection(self) -> Tuple[bool, str]:
        """
        Intenta resetear la conexión con la BD.
        """
        return self.initialize_agent(max_retries=3)
