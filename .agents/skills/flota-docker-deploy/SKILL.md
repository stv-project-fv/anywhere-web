---
name: flota-docker-deploy
description: >-
  Procedimientos seguros para operar el contenedor Docker (panel_flota_app), realizar copias
  de seguridad atómicas de la base SQLite (flota.db) y mantener la compatibilidad de rutas
  con PythonAnywhere (/home/MFVProveedores/mysite). Usar ante tareas de Docker, backups o despliegue.
---

# Operación Docker, Backups SQLite y Despliegue (`flota-docker-deploy`)

Esta skill guía las tareas de infraestructura local con Docker Compose, resguardo de datos SQLite y compatibilidad con PythonAnywhere.

---

## 1. Arquitectura de Contenedor y Volúmenes

- **Servicio Compose**: `web` (nombre de contenedor: `panel_flota_app`, puerto `5000:5000`, servidor `gunicorn --workers 2 --threads 4`).
- **Volumen montado**: `./mi_proyecto/home/MFVProveedores/mysite:/app`
  - **Importante**: La base de datos `flota.db` dentro de `/app/flota.db` en el contenedor es **el mismo archivo físico** que `mi_proyecto/home/MFVProveedores/mysite/flota.db` en el host Windows.
  - `.dockerignore` excluye `*.db`, `*.db-*`, `*.sqlite*` y `*.bak` para que las imágenes construidas con `docker compose build` nunca contengan datos sensibles de la flota en sus capas.

---

## 2. Comandos Operativos Seguros

- **Levantar en segundo plano**: `docker compose up -d`
- **Reconstruir tras cambios en `Dockerfile` o `requirements.txt`**: `docker compose up -d --build`
- **Reiniciar servicio web**: `docker compose restart web`
- **Ver estado y logs**:
  - `docker compose ps`
  - `docker logs --tail 100 panel_flota_app`
- **Ejecutar pruebas aisladas dentro del contenedor**:
  - `docker compose exec web python test_integration.py` *(usa automáticamente un archivo temporal aislado gracias a `FLOTA_DB_PATH`)*.

---

## 3. Respaldo Atómico de `flota.db` (SQLite)

Nunca copiar `flota.db` con `cp`/`Copy-Item` simple mientras haya escrituras activas si es posible usar la API de backup de SQLite. Ejecutar siempre:

```powershell
python -c "import sqlite3; src = sqlite3.connect('mi_proyecto/home/MFVProveedores/mysite/flota.db'); dst = sqlite3.connect('mi_proyecto/home/MFVProveedores/mysite/flota.db.bak'); src.backup(dst); dst.close(); src.close(); print('Backup atómico completado: flota.db.bak')"
```

---

## 4. Compatibilidad Multi-Entorno (Windows / Docker / PythonAnywhere)

- En `flask_app.py` y `db_service.py`, las rutas de archivos (`.env`, `flota.db`, `static/`, `icon-muni.ico`) deben resolverse siempre de forma relativa a `os.path.dirname(os.path.abspath(__file__))` (con fallback a `/home/MFVProveedores/mysite` para PythonAnywhere).
- No introducir rutas absolutas dependientes de Windows (`C:\...`) ni de Linux (`/app/...`) sin fallback relativo.

