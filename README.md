# Monitor BBDD Oracle (SIMBA)

SIMBA es un agente conversacional para monitorización de bases de datos Oracle. El proyecto combina:

- acceso directo a Oracle con python-oracledb
- un agente LLM con LangChain
- herramientas específicas para consultas de rendimiento y bloqueo
- una API REST en FastAPI
- un frontend web ligero en HTML/CSS/JavaScript
- generación de informes HTML en la carpeta reports/
- análisis de informes AWR (RF021) subidos desde la web

El flujo principal es:
1. conectar a la base de datos Oracle
2. construir el agente LLM
3. aceptar preguntas en lenguaje natural
4. ejecutar herramientas de monitorización
5. devolver tablas formateadas o generar un informe HTML

---

## 1. Requisitos previos

- Python 3.10 o superior (recomendado 3.12; versiones muy recientes como 3.15 pueden no tener wheels para algunas dependencias y exigir compilador C++)
- Oracle Instant Client 23ai 64-bit, paquete Basic (solo si usas modo Thick)
- Credenciales válidas de conexión a Oracle
- Una clave API de OpenAI o configuración de GenAI Hub
- Acceso a una base de datos Oracle con permisos de lectura para consultas de monitorización

Importante:
- El proyecto usa python-oracledb (modo Thin por defecto, requiere Oracle Database 12.1+).
- Opcional: para modo Thick, define ORACLE_CLIENT_DIR con la ruta de Oracle Instant Client.
- Si la conexión falla con DPY-3015 (verificador de contraseña 0x939), el usuario tiene un verificador 10G que Thin no soporta: usa modo Thick o pide al DBA que regenere la contraseña.
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

# --- Instant Client (opcional, activa modo Thick; si se omite, modo Thin) ---
# ORACLE_CLIENT_DIR=C:\oracle\instantclient_23_0

# --- API FastAPI ---
SIMBA_CORS_ALLOWED_ORIGINS=*
SIMBA_HOST=127.0.0.1
SIMBA_PORT=8000

# --- Protección de consultas ---
SIMBA_DB_QUERY_TIMEOUT_MS=5000

# --- Informes AWR subidos (RF021) ---
SIMBA_AWR_MAX_MB=20
SIMBA_AWR_MAX_FILES=50
SIMBA_AWR_FOLLOWUP=true
SIMBA_AWR_FOLLOWUP_BUDGET_S=30

# --- Informe HTML (RF006): esquema para el top de tablas ---
REPORT_OWNER=ENET
```

Notas:
- El valor por defecto de SIMBA_CORS_ALLOWED_ORIGINS es "*" para uso local.
- No se recomienda dejarlo abierto si la API va a quedar expuesta fuera de un entorno local o privado.
- El backend y el frontend tienen una intención de uso local, no productivo por defecto.
- GENAIHUB_SCOPE es obligatorio con GenAI Hub (endpoint OAuth v2.0).

---

## 3. Instalación

Desde la raíz del proyecto:

```powershell
cd c:\github\dbAgent
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Si PowerShell bloquea la activación del entorno, ejecuta antes `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, o usa directamente `.\.venv\Scripts\python.exe`.

Si ya existe el entorno virtual:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Dependencias principales:

- langchain
- langchain-openai
- oracledb
- python-dotenv
- jinja2
- tabulate
- fastapi
- uvicorn
- python-multipart

---

## 4. Ejecución en modo consola

Desde la raíz del proyecto:

```powershell
cd c:\github\dbAgent
.\.venv\Scripts\Activate.ps1
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
.\.venv\Scripts\Activate.ps1
python -m uvicorn interface.backend.main:app --reload --host 127.0.0.1 --port 8000
```

También se puede arrancar directamente:

```powershell
cd c:\github\dbAgent
.\.venv\Scripts\Activate.ps1
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
├── awr/
│   └── (informes AWR subidos desde la web)
├── db/
│   ├── __init__.py
│   ├── connection.py
│   └── queries.py
├── docs/
│   ├── awr_example.html
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
│   ├── awr_analyzer.py
│   ├── awr_followup.py
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
- análisis de informes AWR (RF021)

La lista completa está en agent/tools.py.

---

## 8. API REST

El backend FastAPI expone endpoints como:

- GET /api/health (estado de BD y LLM por separado)
- POST /api/chat
- POST /api/reset-connection
- GET /api/download-report/{filename}
- POST /api/awr/upload
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

## 9.1 Informes AWR (RF021)

El análisis está en report/awr_analyzer.py y el seguimiento en vivo en report/awr_followup.py. Se expone como herramienta del agente (`analyze_awr_report`) y como endpoint `POST /api/awr/upload`.

- Desde la web: arrastra el .html sobre el chat o usa el botón "Cargar informe AWR". El resumen no requiere BD ni LLM; el seguimiento en vivo requiere BD conectada.
- **Seguimiento tras el análisis**: al resumir el AWR se ejecutan automáticamente consultas de solo lectura asociadas a los hallazgos (SQL → RF002/RF010, CPU → RF001/RF003, bloqueos → RF005/RF017, esperas → RF015, sesiones → RF014/RF020, memoria → RF008/RF008.1; sin hallazgos → RF007/RF008/RF015) y se comparan los SQL IDs del AWR con el estado actual. El resultado se añade al resumen.
- Seguridad: el contenido del AWR solo selecciona áreas; las acciones salen de una lista blanca fija y los SQL IDs deben tener formato Oracle (13 caracteres alfanuméricos). Hay límite de 12 consultas y presupuesto de tiempo `SIMBA_AWR_FOLLOWUP_BUDGET_S` (30 s). Si no hay BD, se devuelve solo el resumen.
- `SIMBA_AWR_FOLLOWUP=false` desactiva el seguimiento en la subida web (útil si la API se expone sin autenticación).
- Los ficheros se guardan en `awr/` con nombre generado por el servidor (`awr_<dd-mm-YYYY_HH-MM-SS>_<token>.html`) y nunca se sirven de vuelta al navegador.
- Validaciones: extensión .html/.htm, fichero no vacío, cabecera `WORKLOAD REPOSITORY` y tamaño máximo `SIMBA_AWR_MAX_MB` (20 MB por defecto).
- Se conservan como máximo `SIMBA_AWR_MAX_FILES` informes (50 por defecto); se eliminan los más antiguos.
- La herramienta solo analiza `docs/awr_example.html` (valor por defecto) o ficheros dentro de `awr/`.

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
- Si usas modo Thick, revisa que ORACLE_CLIENT_DIR apunte a un Instant Client válido
- Usa una versión 64-bit correcta
- Comprueba que el cliente esté presente en la ruta indicada
- Instala el Visual C++ Redistributable x64 si la DLL no carga

### Error DPY-3015 (password verifier type 0x939)
- El usuario Oracle tiene un verificador de contraseña 10G que el modo Thin no soporta
- Solución rápida: define ORACLE_CLIENT_DIR (modo Thick)
- Solución definitiva: pide al DBA que regenere la contraseña del usuario y permita verificadores 11G/12C

### Error ModuleNotFoundError / fallo al compilar dependencias
- Instala las dependencias con el mismo Python que ejecuta la aplicación (idealmente el del .venv)
- Si pip intenta compilar paquetes (p. ej. zstandard) y falla, usa Python 3.12 o 3.13

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
- subida de informes AWR sin autenticación (mitigada con límite de tamaño, validación de contenido, nombre generado en servidor y rotación de ficheros)

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
- report/awr_analyzer.py para el análisis de informes AWR

