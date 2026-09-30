# Monitor BBDD Oracle (SIMBA)

SIMBA es un agente conversacional para monitorización de bases de datos Oracle. El proyecto combina:

- acceso directo a Oracle con cx_Oracle
- un agente LLM con LangChain
- herramientas específicas para consultas de rendimiento y bloqueo
- una API REST en FastAPI
- un frontend web ligero en HTML/CSS/JavaScript
- generación de informes HTML en la carpeta reports/

El flujo principal es:
1. conectar a la base de datos Oracle
2. construir el agente LLM
3. aceptar preguntas en lenguaje natural
4. ejecutar herramientas de monitorización
5. devolver tablas formateadas o generar un informe HTML

---

## 1. Requisitos previos

- Python 3.10 o superior
- Oracle Instant Client 64-bit instalado y accesible
- Credenciales válidas de conexión a Oracle
- Una clave API de OpenAI o configuración de GenAI Hub
- Acceso a una base de datos Oracle con permisos de lectura para consultas de monitorización

Importante:
- El proyecto usa cx_Oracle.
- La ubicación del client Oracle se toma de la variable ORACLE_CLIENT_DIR.
- El archivo .env debe mantenerse fuera del repositorio.

---

## 2. Configuración del entorno

Crea un archivo .env en la raíz del proyecto a partir de .env.example.

Ejemplo mínimo:

```env
# --- Conexión Oracle ---
DB_HOST=localhost
DB_PORT=1521
DB_SERVICE=ORCLPDB1
DB_USER=monitor_user
DB_PASSWORD=tu_password

# --- LLM ---
LLM_PROVIDER=openai
OPENAI_API_KEY=tu_clave
OPENAI_MODEL=gpt-4o

# Opcional: si usas GenAI Hub en lugar de OpenAI
# LLM_PROVIDER=genaihub
# GENAIHUB_MODEL=...
# GENAIHUB_BASE_URL=...
# GENAIHUB_TENANT_ID=...
# GENAIHUB_TOKEN_URL=...
# GENAIHUB_SCOPE=...
# GENAIHUB_CLIENT_ID=...
# GENAIHUB_CLIENT_SECRET=...
# SSL_VERIFY=false

# --- Instant Client ---
ORACLE_CLIENT_DIR=C:\oracle\instantclient_23_0

# --- API FastAPI ---
SIMBA_CORS_ALLOWED_ORIGINS=*
SIMBA_HOST=127.0.0.1
SIMBA_PORT=8000

# --- Protección de consultas ---
SIMBA_DB_QUERY_TIMEOUT_MS=5000
```

Notas:
- El valor por defecto de SIMBA_CORS_ALLOWED_ORIGINS es "*" para uso local.
- No se recomienda dejarlo abierto si la API va a quedar expuesta fuera de un entorno local o privado.
- El backend y el frontend tienen una intención de uso local, no productivo por defecto.

---

## 3. Instalación

Desde la raíz del proyecto:

```powershell
cd c:\github\dbAgent
python -m venv .venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Si ya existe el entorno virtual:

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Dependencias principales:

- langchain
- langchain-openai
- cx_Oracle
- python-dotenv
- jinja2
- tabulate
- fastapi
- uvicorn

---

## 4. Ejecución en modo consola

Desde la raíz del proyecto:

```powershell
cd c:\github\dbAgent
.\venv\Scripts\Activate.ps1
python main.py
```

Comportamiento:
- intenta conectar a Oracle
- crea el agente LLM
- abre un chat interactivo
- acepta consultas en español
- permite salir con:
  - salir
  - exit
  - quit
  - Ctrl + C

El punto de entrada es main.py.

---

## 5. Ejecución del backend web

Desde la raíz del proyecto:

```powershell
cd c:\github\dbAgent
.\venv\Scripts\Activate.ps1
python -m uvicorn interface.backend.main:app --reload --host 127.0.0.1 --port 8000
```

También se puede arrancar directamente:

```powershell
cd c:\github\dbAgent
.\venv\Scripts\Activate.ps1
python interface\backend\main.py
```

La API queda disponible en:

```text
http://127.0.0.1:8000
```

El frontend se sirve desde la carpeta interface/frontend y el backend está en interface/backend.

---

## 6. Estructura del proyecto

```text
dbAgent/
├── .env.example
├── .gitignore
├── main.py
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
├── README.md
├── agent/
│   ├── __init__.py
│   ├── agent.py
│   └── tools.py
├── db/
│   ├── __init__.py
│   ├── connection.py
│   └── queries.py
├── docs/
│   ├── example.html
│   ├── funtionalRequirements.md
│   ├── GenAIHub.md
│   └── newQueries.txt
├── interface/
│   ├── README.md
│   ├── __init__.py
│   ├── backend/
│   │   ├── __init__.py
│   │   ├── api_handlers.py
│   │   └── main.py
│   └── frontend/
│       ├── app.js
│       ├── index.html
│       └── styles.css
├── report/
│   ├── __init__.py
│   ├── generator.py
│   └── template.html
├── reports/
│   └── (informes HTML generados)
├── tests/
│   ├── conftest.py
│   ├── api/
│   ├── report/
│   └── unit/
└── conftest.py
```

---

## 7. Qué puede hacer el agente

El agente expone una serie de herramientas de monitorización Oracle, entre ellas:

- CPU actual
- consultas más costosas
- sesiones con más CPU
- usuarios con sesiones inactivas
- sesiones bloqueantes
- SQLs bloqueantes
- total de sesiones bloqueadas
- resumen general de la base de datos
- métricas de rendimiento y SGA
- sesiones activas
- detalle por SQL ID
- sesiones por programa, usuario, módulo
- detección de pooling
- métricas de espera/latencia
- top tablas por tamaño
- detección de bloqueos entre tablas
- métricas de sysmetric
- total de sesiones conectadas
- generación de informe HTML

La lista completa está en agent/tools.py.

---

## 8. API REST

El backend FastAPI expone endpoints como:

- GET /api/health
- POST /api/chat
- POST /api/reset-connection
- GET /api/download-report/{filename}
- GET /api/chat-history
- POST /api/clear-history

Más detalles en interface/backend/main.py y interface/backend/api_handlers.py.

Notas importantes:
- Se gestiona un historial aislado por sesión con X-Session-Id.
- La conexión a Oracle y la inicialización del LLM se gestionan por separado.
- La API está pensada para uso local; no es una API segura para exposición pública sin revisión adicional.

---

## 9. Informes HTML

El generador de informes se encuentra en report/generator.py.

Genera ficheros con nombre tipo:

```text
dbCheck_17-09-2026_12-39.html
```

Los informes se guardan en la carpeta:

```text
reports/
```

El nombre incluye día, mes, año, hora y minutos.

---

## 10. Pruebas automatizadas

Se usa pytest con mocks para simular:

- Oracle
- LLM
- consultas
- generación de informes
- API REST

Para ejecutar las pruebas:

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

Las pruebas cubren:
- unit tests de queries y herramientas
- tests de report generation
- tests de API

No hace falta Oracle real ni un LLM real para ejecutar la suite principal.

---

## 11. Solución de problemas comunes

### Error DPI-1047
- Revisa que ORACLE_CLIENT_DIR apunte a un Instant Client válido
- Usa una versión 64-bit correcta
- Comprueba que el cliente esté presente en la ruta indicada

### Error de conexión a base de datos
- Revisa DB_HOST, DB_PORT, DB_SERVICE, DB_USER, DB_PASSWORD
- Asegúrate de que la base de datos esté accesible desde el entorno local
- Comprueba que el usuario tenga permisos de lectura suficientes para las consultas

### Error al inicializar el agente LLM
- Revisa OPENAI_API_KEY o la configuración de GenAI Hub
- Verifica que LLM_PROVIDER sea el esperado
- Si usas GenAI Hub, comprueba GENAIHUB_CLIENT_ID, GENAIHUB_CLIENT_SECRET y GENAIHUB_SCOPE

### La API no responde
- Comprueba que uvicorn está arrancado
- Revisa la salida de la consola
- Verifica el puerto configurado en SIMBA_PORT

---

## 12. Seguridad y límites actuales

Este proyecto no pretende ser una capa de seguridad de producción por defecto. El enfoque actual es operativo y local.

Riesgos actuales documentados en código:
- CORS abierto por defecto
- ausencia de autenticación/autorización en la API
- uso local del backend y del frontend
- exposición de errores internos en endpoints de estado
- conexión Oracle y agente LLM con reintentos independientes

Antes de cualquier despliegue real, sería necesario:
- restringir CORS a orígenes concretos
- proteger la API con autenticación
- controlar quién puede acceder al puerto de la aplicación
- revisar regímenes de secretos y entorno
- valorar si la aplicación requiere aislamiento multiusuario

---

## 13. Resumen

SIMBA es un monitor de Oracle orientado a diagnóstico rápido de:
- carga de CPU
- sesiones activas/inactivas
- bloqueos
- uso de memoria y SGA
- volumen de acceso
- patrones de conexión
- flags de riesgo de rendimiento

La parte más relevante del sistema está en:
- db/queries.py para la lógica SQL
- agent/tools.py para la capa de exposición del agente
- agent/agent.py para la configuración del LLM
- interface/backend/api_handlers.py para chat y sesiones
- report/generator.py para reportes HTML

