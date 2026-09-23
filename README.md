# Monitor BBDD Oracle (SIMBA)

Guia de arranque del proyecto para:
- modo consola (archivo `main.py` en la raiz)
- modo web (FastAPI + frontend en `interface/`)

## Requisitos previos

- Python 3.10 o superior
- Acceso a Oracle con credenciales validas
- Oracle Instant Client instalado (64-bit)

Importante:
- Este proyecto usa `cx_Oracle`, por lo que necesitas tener configurado `ORACLE_CLIENT_DIR` en tu `.env`.

## 1) Configurar variables de entorno

En la raiz del proyecto (`c:\github\dbAgent`) crea o actualiza el archivo `.env`.

Puedes partir de `.env.example` y completar, como minimo:

```env
DB_HOST=...
DB_PORT=1521
DB_SERVICE=...
DB_USER=...
DB_PASSWORD=...

OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o

ORACLE_CLIENT_DIR=C:\oracle\instantclient_23_0
```

## 2) Instalar dependencias

Desde la raiz del proyecto:

```powershell
cd c:\github\dbAgent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Si ya tienes el entorno virtual creado, solo activalo y ejecuta `pip install -r requirements.txt`.

## 3) Ejecutar modo consola

Desde la raiz del proyecto:

```powershell
cd c:\github\dbAgent
.\.venv\Scripts\Activate.ps1
python main.py
```

Comportamiento esperado:
- intenta conectar a Oracle
- si conecta, arranca el chat en consola (`Tu:` / `Simba:`)
- para salir: `salir` o `Ctrl + C`

## 4) Ejecutar modo web

Opcion A (recomendada, desde raiz):

```powershell
cd c:\github\dbAgent
.\.venv\Scripts\Activate.ps1
python -m uvicorn interface.backend.main:app --reload --host 127.0.0.1 --port 8000
```

Opcion B (equivalente, ejecutando el backend directamente):

```powershell
cd c:\github\dbAgent
.\.venv\Scripts\Activate.ps1
python interface\backend\main.py
```

Luego abre en el navegador:

```text
http://127.0.0.1:8000
```

## 5) Carpetas de salida

- Informes RF006: `reports/`

## 6) Comandos rapidos

Instalar todo:

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1; python -m pip install --upgrade pip; pip install -r requirements.txt
```

Consola:

```powershell
.\.venv\Scripts\Activate.ps1; python main.py
```

Web:

```powershell
.\.venv\Scripts\Activate.ps1; python -m uvicorn interface.backend.main:app --reload --host 127.0.0.1 --port 8000
```

## 7) Problemas comunes

- Error `DPI-1047`:
	- revisa que `ORACLE_CLIENT_DIR` apunte a un Instant Client 64-bit valido.
- Error de conexion a BD:
	- valida `DB_HOST`, `DB_PORT`, `DB_SERVICE`, `DB_USER`, `DB_PASSWORD`.

