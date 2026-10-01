# Especificación funcional del proyecto SIMBA

## 1. Objetivo del sistema

SIMBA es un agente conversacional orientado a la monitorización operativa de bases de datos Oracle. Su finalidad es permitir a un administrador o responsable de soporte consultar el estado de la base de datos en lenguaje natural sin ejecutar manualmente SQL complejos.

El sistema combina:
- conexión Oracle con cx_Oracle
- herramientas de consulta de rendimiento
- un modelo LLM para interpretar peticiones naturales
- un backend REST para interacción web
- generación de informes HTML para análisis posterior

---

## 2. Alcance funcional

El sistema debe permitir:

- consultar el estado actual de CPU
- identificar SQLs con mayor consumo de CPU
- analizar sesiones activas e inactivas
- detectar bloqueos y sesiones bloqueantes
- obtener resúmenes de rendimiento global
- consultar métricas del sistema Oracle
- revisar uso de SGA
- consultar top tablas por tamaño
- detectar patrones de pooling
- inspeccionar bloqueos entre tablas
- generar un informe HTML en la carpeta reports/

---

## 3. Actores y contexto de uso

### Actores
- Administrador de base de datos
- Soporte técnico
- Desarrollador o analista operativo

### Contexto
- La solución está orientada principalmente a uso local.
- La base de datos debe ser accesible desde la máquina donde ejecuta SIMBA.
- El usuario se comunica con el agente mediante consola o mediante la API REST/web.

---

## 4. Arquitectura funcional

### 4.1 Capa de conexión
- `db/connection.py`
- gestiona la conexión singleton a Oracle
- usa variables de entorno como DB_HOST, DB_PORT, DB_SERVICE, DB_USER y DB_PASSWORD
- inicializa instant client con ORACLE_CLIENT_DIR

### 4.2 Capa de consultas
- `db/queries.py`
- define una función por requisito funcional
- aplica timeout por query usando SIMBA_DB_QUERY_TIMEOUT_MS
- protege resultados con límite defensivo HARD_ROW_LIMIT = 500

### 4.3 Capa de herramientas del agente
- `agent/tools.py`
- expone cada RF como herramienta LangChain
- devuelve resultados en formato tabular legible para el LLM

### 4.4 Capa de orquestación LLM
- `agent/agent.py`
- construye el agente con ChatOpenAI
- soporta OpenAI y GenAI Hub
- define un prompt con la capacidad operativa del monitor

### 4.5 API y frontend
- `interface/backend/main.py`
- `interface/backend/api_handlers.py`
- `interface/frontend/index.html`
- `interface/frontend/app.js`

La API gestiona:
- chat
- historial por sesión
- salud del sistema
- reinicio de conexión
- descarga de informes HTML

---

## 5. Flujo de uso principal

1. El usuario inicia la aplicación en consola o web.
2. El sistema intenta conectar a Oracle.
3. El agente se inicializa con el proveedor LLM configurado.
4. El usuario realiza una pregunta natural.
5. El agente decide qué herramienta ejecutar.
6. La consulta se ejecuta contra Oracle.
7. Se formatea el resultado en texto/tablas.
8. Si la petición requiere un informe completado, se genera un archivo HTML en reports/

---

## 6. Requisitos funcionales implementados

### RF001 — CPU actual
- **Descripción**: devuelve el porcentaje de CPU que está usando la base de datos en ese momento.
- **Fuente**: get_cpu_usage
- **Resultado**: valor porcentual con 2 decimales

### RF002 — Top SQLs por CPU
- **Descripción**: muestra las consultas con mayor consumo de CPU.
- **Parámetro**: limit (por defecto 5)
- **Resultado**: usuario, ejecuciones, porcentaje de CPU, cpu_time y SQL

### RF003 — Top sesiones por CPU
- **Descripción**: muestra las sesiones activas con mayor consumo de CPU.
- **Parámetro**: limit
- **Resultado**: SID, SERIAL, usuario, CPU total y porcentaje

### RF004 — Usuarios con sesiones inactivas
- **Descripción**: lista usuarios con más sesiones inactivas > 30 minutos.
- **Parámetro**: limit
- **Resultado**: usuario, número de sesiones inactivas y porcentaje de CPU

### RF004.1 — Detalle de sesiones inactivas
- **Descripción**: lista sesiones inactivas o huérfanas con más de 30 minutos de inactividad.
- **Parámetro**: limit
- **Resultado**: SID, SERIAL, usuario, idle, CPU, memoria, máquina y logon time

### RF004.2 — Total de sesiones inactivas
- **Descripción**: devuelve el número total de sesiones inactivas > 30 minutos.
- **Resultado**: número entero

### RF004.3 — Sesiones inactivas de un usuario
- **Descripción**: devuelve las sesiones inactivas de un usuario concreto.
- **Parámetros**: username, limit
- **Resultado**: detalle de sesiones

### RF004.4 — Total de sesiones inactivas por usuario
- **Descripción**: devuelve el total de sesiones inactivas de un usuario concreto.
- **Parámetro**: username
- **Resultado**: número entero

### RF005 — Sesiones bloqueantes
- **Descripción**: identifica sesiones que están bloqueando a otras.
- **Parámetro**: limit
- **Resultado**: SID, SERIAL, usuario y máquina

### RF005.1 — SQL de sesiones bloqueantes
- **Descripción**: identifica SQLs asociadas a sesiones bloqueantes.
- **Parámetro**: limit
- **Resultado**: blocker SID, usuario, sesiones bloqueadas, SQL ID y SQL

### RF005.2 — Total de SQLs bloqueantes
- **Descripción**: total de SQLs asociadas a bloqueos.
- **Resultado**: entero

### RF005.3 — Total de sesiones bloqueadas
- **Descripción**: total de sesiones bloqueadas en el instante actual.
- **Resultado**: entero

### RF006 — Generación de informe HTML
- **Descripción**: genera un informe completo con el estado del sistema.
- **Resultado**: archivo HTML guardado en reports/
- **Nombre**: dbCheck_DD-MM-YYYY_HH-MM.html

### RF007 — Resumen general de la base de datos
- **Descripción**: proporciona un resumen agrupado de métricas clave.
- **Resultado**: tabla con nombre de métrica y valor

### RF008 — Métricas de rendimiento
- **Descripción**: devuelve métricas de performance relevantes.
- **Resultado**: listado de métricas y valores

### RF008.1 — Detalle de SGA
- **Descripción**: obtiene información del SGA.
- **Resultado**: nombre, bytes y si es redimensionable

### RF009 — Usuarios con más sesiones activas
- **Descripción**: devuelve usuarios con más sesiones activas.
- **Parámetro**: limit
- **Resultado**: usuario, número de sesiones activas y porcentaje de CPU

### RF009.1 — Detalle de sesiones activas
- **Descripción**: lista sesiones activas con detalle.
- **Parámetro**: limit
- **Resultado**: SID, usuario, SQL ID, tiempo activo, CPU, memoria, máquina y logon time

### RF009.2 — Total de sesiones activas
- **Descripción**: devuelve el total de sesiones activas.
- **Resultado**: entero

### RF009.3 — Sesiones activas por usuario
- **Descripción**: devuelve detalle de sesiones activas de usuario concreto.
- **Parámetros**: username, limit

### RF009.4 — Total de sesiones activas por usuario
- **Descripción**: devuelve total de sesiones activas de un usuario concreto.
- **Parámetros**: username

### RF010 — Información de SQL por SQL ID
- **Descripción**: busca detalle de una sentencia SQL concreta.
- **Parámetro obligatorio**: sql_id
- **Resultado**: sesiones asociadas, estado, tiempos y SQL text

### RF011 — Sesiones por programa y máquina
- **Descripción**: agrupa sesiones por programa y máquina de origen.
- **Parámetro**: limit
- **Resultado**: programa, máquina y número de sesiones

### RF012 — Sesiones por usuario
- **Descripción**: agrupa sesiones por usuario y estado.
- **Parámetro**: limit
- **Resultado**: usuario, estado y número de sesiones

### RF013 — Sesiones por módulo
- **Descripción**: agrupa sesiones por módulo de aplicación.
- **Parámetro**: limit
- **Resultado**: módulo y número de sesiones

### RF014 — Detección de pooling
- **Descripción**: detecta patrones de alta concurrencia por programa, máquina y usuario.
- **Parámetros**: threshold, limit
- **Resultado**: combinaciones que superan el umbral establecido

### RF015 — Métricas de latencia y waits
- **Descripción**: devuelve métricas de espera o latencia relevantes.
- **Resultado**: nombre de métrica y valor

### RF016 — Top tablas por tamaño
- **Descripción**: muestra tablas más grandes por esquema.
- **Parámetros**: owner, limit
- **Resultado**: owner, tabla, tamaño en MB y GB

### RF017 — Detección de bloqueos entre tablas
- **Descripción**: identifica bloqueos entre sesiones y objetos.
- **Parámetro**: limit
- **Resultado**: holder, recurso, tipo, modo, waiter y SQL de espera

### RF018 — Métricas de sesiones y usuarios por sysmetric
- **Descripción**: muestra métricas agregadas de v$sysmetric relacionadas con sesiones y usuarios.
- **Resultado**: nombre de métrica y valor

### RF019 — Total de sesiones por usuario y estado
- **Descripción**: cuenta sesiones agrupadas por usuario Oracle y estado.
- **Resultado**: usuario, estado y total

### RF020 — Total de sesiones conectadas
- **Descripción**: devuelve el total de sesiones conectadas.
- **Resultado**: número total de sesiones, además de activas e inactivas > 30 minutos

### RF021 — Análisis de informe AWR
- **Descripción**: analiza un informe HTML de AWR y devuelve un resumen ejecutivo con base de datos, instantáneas, instancias, hallazgos de ADDM y recomendaciones de seguimiento.
- **Parámetro**: file_path (nombre de un informe de la carpeta awr/ o docs/awr_example.html, valor por defecto). Cualquier otra ruta se rechaza.
- **Carga desde la web**: el usuario arrastra y suelta el .html sobre el chat (o usa el botón "Cargar informe AWR"). El fichero se envía a `POST /api/awr/upload` (multipart, campo `file`), se guarda en `./awr` con un nombre generado por el servidor (`awr_<dd-mm-YYYY_HH-MM-SS>_<token>.html`) y se analiza al momento, sin necesitar BD ni LLM. El resumen se añade al historial de la sesión para poder hacer preguntas de seguimiento.
- **Validaciones**: extensión .html/.htm, fichero no vacío, contenido con la cabecera `WORKLOAD REPOSITORY`, tamaño máximo `SIMBA_AWR_MAX_MB` (20 MB por defecto). Se conservan como máximo `SIMBA_AWR_MAX_FILES` informes (50 por defecto), eliminando los más antiguos.
- **Resultado**: texto resumido, legible para un usuario no experto, con la guía de qué RF de monitorización en vivo puede usar para contrastar la causa real

---

## 7. Reglas de negocio y comportamiento

- Cuando el usuario no especifique un número concreto, el sistema devuelve 5 resultados por defecto.
- Si la operación necesita un parámetro obligatorio y no está presente, el agente debe pedirlo.
- Las respuestas se devuelven en español.
- Si la consulta no puede resolverse con las herramientas disponibles, el sistema lo indica explícitamente.
- Las consultas deben protegerse con timeout y límite defensivo de filas.
- Los informes se generan en el directorio reports/ y usan un nombre generado automáticamente.
- Los informes AWR subidos desde la web se almacenan en el directorio awr/ y nunca se sirven de vuelta al navegador.

---

## 8. Seguridad y restricciones operativas

El proyecto tiene un enfoque local y no productivo por defecto.

**Riesgos aceptados**:
- API sin autenticación para uso local
- CORS abierto en entorno local
- acceso directo sin filtro de orígenes externos
- exposición de errores internos en algunos endpoints de salud
- Gestión independiente de reintentos para conexión Oracle y agente LLM
- Timeout de conexión a nivel de query con límite defensivo de 500 filas
- Subida de informes AWR sin autenticación: con CORS abierto, cualquier web abierta en el navegador podría enviar ficheros al servidor local (mitigado con límite de tamaño, validación de contenido, nombre generado en servidor y rotación de ficheros)

**Recomendaciones antes de exposición real**:
- cerrar CORS a orígenes concretos
- proteger la API con autenticación/authorization
- restringir los puertos y hosts
- revisar secretos y variables de entorno
- separar entornos de desarrollo, pruebas y producción
- implementar logging y auditoría

---

## 9. Salidas esperadas

El sistema debe poder dar como salida:

- tablas con resultados de consulta
- texto resumido en español
- mensajes de error claros
- archivo HTML generado con un resumen del estado de la base de datos

---

## 10. Criterio de aceptación

El proyecto se considera funcional cuando:

1. conecta a Oracle con las credenciales configuradas
2. responde preguntas sobre rendimiento y bloqueo en lenguaje natural
3. devuelve resultados tabulares legibles
4. soporta la generación de informes HTML
5. permite uso desde consola y desde API web
6. mantiene la configuración centralizada en .env
7. aplica límites y timeout a las consultas para evitar bloqueos prolongados
