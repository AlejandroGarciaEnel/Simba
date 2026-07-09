# dbAgent - Interfaz Web

Interfaz conversacional web estilo Gemini para el monitor de base de datos Oracle.

## 🚀 Inicio Rápido

### 1. Instalar dependencias

```bash
pip install -r ../requirements.txt
```

Las nuevas dependencias requeridas:
- `fastapi>=0.100.0`
- `uvicorn[standard]>=0.23.0`

### 2. Iniciar el servidor backend

```bash
cd backend
python main.py
```

O con uvicorn:

```bash
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

### 3. Acceder a la interfaz

Abre tu navegador en: **http://localhost:8000**

---

## 📋 Características

✅ **Chat conversacional** — Interfaz estilo Gemini con historial  
✅ **Dark mode** — Tema oscuro/claro persistente en navegador  
✅ **Markdown rendering** — Soporte para formato de texto enriquecido  
✅ **Tablas interactivas** — Renderización de datos tabulares  
✅ **Acciones rápidas** — Botones de atajos para queries comunes  
✅ **Descarga automática de informes** — Genera HTML al solicitarlo  
✅ **3 reintentos de conexión** — Manejo automático de fallos BD  
✅ **Botón de reintento manual** — Intenta reconectar cuando falla  
✅ **Historial por sesión** — localStorage (se pierde al cerrar navegador)  
✅ **Responsive** — Funciona en móvil, tablet y desktop  

---

## 🏗️ Arquitectura

```
┌─────────────────────────────────────┐
│  Frontend (HTML + CSS + Vanilla JS)  │
│  - index.html → estructura           │
│  - styles.css → estilos              │
│  - app.js → lógica interactiva       │
└────────────┬────────────────────────┘
             │ HTTP (fetch)
             ▼
┌─────────────────────────────────────┐
│  Backend (FastAPI)                   │
│  - main.py → servidor REST           │
│  - api_handlers.py → adaptador       │
└────────────┬────────────────────────┘
             │ importa
             ▼
┌─────────────────────────────────────┐
│  Agente Existente                    │
│  - agent/agent.py (LangChain)        │
│  - db/connection.py (Oracle)         │
│  - db/queries.py (SQL)               │
│  - report/generator.py (HTML)        │
└─────────────────────────────────────┘
```

---

## 📡 API Endpoints

### `GET /api/health`
Verifica el estado del servidor y conexión BD.

**Response:**
```json
{
    "status": "ok",
    "db_connected": true,
    "message": "Servidor activo"
}
```

### `POST /api/chat`
Envía un mensaje y recibe respuesta del agente.

**Request:**
```json
{
    "message": "¿Cuánta CPU está usando la base de datos?",
    "history": [...]
}
```

**Response:**
```json
{
    "success": true,
    "message": "El uso actual de CPU es del 45.23%",
    "error": false,
    "is_report": false,
    "can_retry": false,
    "report": null
}
```

### `POST /api/reset-connection`
Intenta resetear la conexión con la BD (3 reintentos automáticos).

**Response:**
```json
{
    "success": true,
    "message": "Conexión establecida correctamente",
    "db_connected": true
}
```

### `GET /api/download-report/{filename}`
Descarga un informe HTML generado.

### `GET /api/chat-history`
Retorna el historial de chat del servidor.

### `POST /api/clear-history`
Limpia el historial del servidor.

---

## ⚙️ Configuración

El backend hereda todas las variables de entorno del `.env` en la raíz del proyecto:

```env
# Oracle Database
DB_HOST=localhost
DB_PORT=1521
DB_USER=mon_user
DB_PASSWORD=password
DB_SID=ORCL

# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
```

---

## 🔄 Flujo de Descarga de Informe

1. Usuario pregunta: *"Genera un informe"*
2. Frontend envía mensaje a `/api/chat`
3. Backend detecta solicitud RF006 y genera HTML
4. Respuesta incluye `is_report: true` y datos del archivo
5. JavaScript descarga automáticamente el `.html`
6. Se muestra notificación de éxito

---

## 🛠️ Desarrollo

### Estructura de directorios

```
interface/
├── __init__.py
├── README.md (este archivo)
├── backend/
│   ├── __init__.py
│   ├── main.py (servidor FastAPI)
│   └── api_handlers.py (adaptador agente)
└── frontend/
    ├── index.html
    ├── styles.css
    └── app.js
```

### Modificar estilos

- **Colores**: Editar variables CSS en `styles.css` (`:root`)
- **Layout**: Modificar flexbox/grid en `styles.css`
- **Tema**: Agregar nuevas clases en `body.dark-theme`

### Agregar features

- **Nuevos endpoints**: Editar `backend/main.py`
- **Lógica de chat**: Modificar `api_handlers.py` (ChatHandler)
- **UI**: Actualizar `index.html` y `app.js`

---

## 🐛 Troubleshooting

### "Error de conexión con la BD"

1. Verifica variables de entorno en `.env`
2. Comprueba que Oracle está accesible
3. Intenta con el botón "Reintentar"
4. Revisa logs del servidor

### "El agente no responde"

- Verifica que OPENAI_API_KEY está configurada
- Comprueba conexión a Internet
- Revisa la consola del navegador (F12)

### "El informe no descarga"

- Asegúrate de que la BD responde
- Comprueba permisos de lectura
- Revisa que `report/generator.py` existe

---

## 📝 Notas

- **Historial**: Se guarda en `localStorage` (sesión actual solamente)
- **Persistencia**: Para guardar entre sesiones, descarga regularmente tus informes
- **Seguridad**: La API valida nombres de archivo antes de descargar
- **Performance**: El frontend es ultraligero (sin frameworks)

---

## 🚀 Próximas mejoras

- [ ] Historial persistente en backend (JSON/SQLite)
- [ ] Tabla de resultados con ordenamiento interactivo
- [ ] Exportar chat a PDF/TXT
- [ ] Autenticación de usuario
- [ ] Tema personalizado (colores custom)
- [ ] Soporte multiidioma

---

**¿Problemas?** Revisa los logs del servidor: `VSCODE_TARGET_SESSION_LOG`
