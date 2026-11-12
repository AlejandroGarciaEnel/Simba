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

### Acceso por roles

La web exige iniciar sesión. Los usuarios se guardan en `data/users.json` (ignorado por git, contraseñas
con hash PBKDF2-SHA256). El primer administrador se crea desde consola:

```bash
python -m interface.backend.auth crear-usuario mario --rol administrador
```

| Rol | Puede |
|---|---|
| `consulta` | Ver el panel de estado, el histórico y usar el asistente |
| `dba` | Además: forzar una revisión nueva, ver el detalle técnico, subir AWR y reiniciar la conexión |
| `administrador` | Además: gestionar usuarios desde la pestaña *Usuarios* |

El panel de estado no usa IA (revisión determinista con caché). El asistente es un panel lateral opcional
que solo consume LLM cuando el usuario le pregunta. Variables: `SIMBA_USERS_FILE`, `SIMBA_SESSION_HOURS`
(8 por defecto) y `SIMBA_COOKIE_SECURE` (activar con HTTPS). Tras 5 intentos fallidos el usuario queda
bloqueado 5 minutos.

Si hay bloqueos, la tarjeta *Bloqueos* lista **todas** las sesiones bloqueantes raíz (instancia, SID/serial,
usuario, máquina, programa, estado, a cuántas bloquea, objeto y SQL), y el asistente las enumera.

### Mejoras de queries (informe semanal)

La pestaña *Queries* y la herramienta del asistente `get_query_improvement_recommendations` leen, solo en
lectura, los Excel del informe semanal de SQL más costosas y la hoja *Seguimiento* del proyecto de mejoras.
Sin IA, señalan: SQL nuevas en el top sin seguimiento, completadas que siguen en el top tras una semana
completa, mejoras estancadas (4+ semanas), completadas sin medir o que empeoran, y pistas técnicas (varios
planes, muchas lecturas por fila, exceso de ejecuciones, PL/SQL, batch pesado). Los textos están en
`query_reports/recommendations.json` para que el DBA los revise. Variables: `SIMBA_QUERY_REPORTS_DIR`
(carpeta con `PRAGU4E_Informe_Semana_*.xlsx`) y `SIMBA_QUERY_TRACKING_FILE` (opcional, `PRAGU4E_Seguimiento.xlsx`).

### Modo presentación

El botón con el ojo (junto al tema, en la barra lateral) activa el *modo presentación* para enseñar SIMBA o
hacer capturas sin datos reales. Todo ocurre en el navegador (`interface/frontend/js/present.js`), también en
`/inactivas`: personas, usuarios, esquemas, usuarios de SO, máquinas, tablespaces y objetos se sustituyen por
seudónimos estables (`Persona A`, `ESQUEMA_01`, `equipo-01`, `TS_DATOS_01`…), el texto SQL conserva su
estructura pero oculta identificadores y literales, y las notas del seguimiento se ocultan. Los seudónimos se
traducen de vuelta al hacer peticiones (filtros, descargas, preguntas al asistente); mientras está activo no
se pueden guardar notas del tablero. Al activarlo se vacía el historial del asistente guardado en el navegador.

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
│       ├── js/
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
- POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me
- POST /api/health-check, GET /api/health-history, GET /api/health-check/{id}/detail (dba)
- GET/POST /api/users, PATCH/DELETE /api/users/{username} (administrador)

Todos los endpoints salvo el login requieren sesión (cookie `simba_session`).

Más detalles en interface/backend/main.py y interface/backend/api_handlers.py.

Notas importantes:
- Se gestiona un historial aislado por sesión con X-Session-Id.
- La conexión a Oracle y la inicialización del LLM se gestionan por separado.
- La API está pensada para uso local; no es una API segura para exposición pública sin revisión adicional.

---

## 9. Revisión de estado (RF022)

`health/checker.py` ejecuta una revisión única sin LLM (CPU, bloqueos con causa probable, límites de
conexiones, tablespaces/TEMP/UNDO, sesiones inactivas, problemas de Oracle registrados en el ADR, esperas y operaciones
largas), aplica reglas de DBA y guarda el resultado en ficheros JSON Lines (`data/health/checks.jsonl` y
`data/health/requests.jsonl`, ignorados por git; no se usa ninguna base de datos).

- Caché: se reutiliza la última revisión durante `SIMBA_HEALTH_CACHE_MINUTES` (10 por defecto).
- Histórico: cada pregunta queda registrada con su fecha, quién preguntó y la revisión devuelta.
- API: `POST /api/health-check?force=true|false` y `GET /api/health-history?limit=20`.
- Algunas comprobaciones requieren permisos (`DBA_TABLESPACE_USAGE_METRICS`, `V$DIAG_PROBLEM`); si
  faltan, se marcan como "No disponible" sin abortar la revisión.
- Errores: se usa `V$DIAG_PROBLEM` (instancia conectada) en lugar de `V$DIAG_ALERT_EXT`, que lee el alert
  log completo y tardaba más de un minuto. Un problema aparecido en el último día se marca como nuevo; uno
  que se repite desde hace tiempo se informa como conocido.
- El bot nunca ejecuta acciones sobre la BD: solo sugiere. Las recomendaciones viven en
  `health/recommendations.json` (plantilla pendiente de revisión por el DBA; se edita sin tocar código) y
  cada revisión recuerda que el equipo funcional debe verificarlas antes de actuar.

---

## 10. Informes HTML

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

Frontal (helpers de `interface/frontend/js/`, requiere Node 20+):

```powershell
npm install
npm test            # node --test tests/frontend/
npm run build:css   # regenera vendor/tailwind-*.css tras usar clases nuevas de Tailwind
```

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
- CORS abierto por defecto (mitigado por la cookie de sesión SameSite=strict)
- autenticación local básica: usuarios en fichero JSON y sesiones en memoria (se pierden al reiniciar)
- uso local del backend y del frontend
- exposición de errores internos en endpoints de estado
- conexión Oracle y agente LLM con reintentos independientes
- subida de informes AWR sin autenticación (mitigada con límite de tamaño, validación de contenido, nombre generado en servidor y rotación de ficheros)

Antes de cualquier despliegue real, sería necesario:
- restringir CORS a orígenes concretos
- integrar la autenticación con el directorio corporativo (LDAP/SSO) y servir por HTTPS
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


### Seguimiento de queries: tablero, lista y análisis DBA

- La pestaña **Queries** ofrece tres vistas del seguimiento semanal: **Tablero** (columnas por estado, estilo Jira), **Lista** (tabla ordenable) y **Recomendaciones**. El tablero es de solo lectura: el Excel de seguimiento sigue siendo la fuente.
- Rol **dba** o superior: `GET /api/sql-analysis/{sql_id}` y la herramienta del agente `analyze_sql_performance` analizan una SQL en la BD (solo SELECT). Revisan los cursores, los planes AWR de 30 días, la tendencia de 14 días, las estadísticas, los índices, los baselines y las SQL hijas de PL/SQL. Con esos datos generan recomendaciones que el equipo funcional debe verificar.
