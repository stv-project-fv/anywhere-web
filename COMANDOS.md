# 🐳 Guía de Comandos Docker - Panel Flota

Este documento reúne los comandos esenciales y avanzados para gestionar, depurar y mantener el contenedor de la aplicación Flask.

---

## 🚀 1. Ciclo de Vida y Operación Básica (Docker Compose)

| Acción | Comando | Descripción |
|---|---|---|
| **Iniciar en segundo plano** | `docker compose up -d` | Levanta el contenedor en segundo plano (detached mode). |
| **Iniciar y reconstruir imagen** | `docker compose up -d --build` | Reconstruye la imagen (ej: tras cambiar `requirements.txt` o `Dockerfile`) y reinicia. |
| **Detener contenedores** | `docker compose down` | Apaga y remueve los contenedores y la red creada. |
| **Detener sin remover** | `docker compose stop` | Detiene la ejecución sin eliminar el contenedor. |
| **Reanudar contenedor detenido** | `docker compose start` | Inicia un contenedor que fue pausado/detenido con `stop`. |
| **Reiniciar servicio** | `docker compose restart web` | Reinicia rápidamente el proceso de la aplicación. |
| **Ver estado de los servicios** | `docker compose ps` | Lista el estado, puertos y nombres de los contenedores del proyecto. |

---

## 📜 2. Monitoreo y Logs

| Acción | Comando |
|---|---|
| **Seguir logs en tiempo real** | `docker logs -f panel_flota_app` |
| **Ver últimas N líneas de log** | `docker logs --tail 100 panel_flota_app` |
| **Ver logs con marcas de tiempo (timestamp)** | `docker logs -tf panel_flota_app` |
| **Ver uso de CPU, RAM y Red en vivo** | `docker stats panel_flota_app` |

---

## 🔍 3. Acceso a la Terminal / Depuración dentro del Contenedor

| Acción | Comando | Descripción |
|---|---|---|
| **Abrir consola interactiva (Bash)** | `docker exec -it panel_flota_app /bin/bash` | Entra a la consola Linux del contenedor para inspeccionar archivos o ejecutar scripts. |
| **Abrir consola con Compose** | `docker compose exec web bash` | Equivalente usando Docker Compose. |
| **Probar Python interactivo dentro del contenedor** | `docker compose exec web python` | Abre la consola interactiva de Python con todas las dependencias instaladas. |
| **Ver procesos activos dentro del contenedor** | `docker top panel_flota_app` | Muestra los procesos Gunicorn y Workers corriendo. |

---

## 💾 4. Gestión de Archivos y Datos Locales (CSVs / Backups)

Dado que el directorio local `./mi_proyecto/home/MFVProveedores/mysite` está montado en `/app`, los archivos generados (como `estado_repuestos.csv` o `cronograma_preventivo.csv`) se guardan directamente en tu máquina local.

| Acción | Comando |
|---|---|
| **Copiar un archivo desde el contenedor a la máquina local** | `docker cp panel_flota_app:/app/estado_repuestos.csv ./backup_repuestos.csv` |
| **Copiar un archivo desde la máquina local al contenedor** | `docker cp ./archivo.csv panel_flota_app:/app/archivo.csv` |

---

## 🧹 5. Mantenimiento y Limpieza de Docker

| Acción | Comando | Descripción |
|---|---|---|
| **Listar imágenes descargadas/creadas** | `docker images` | Muestra el tamaño y tags de las imágenes en el sistema. |
| **Eliminar imágenes huérfanas (dangling)** | `docker image prune` | Libera espacio eliminando capas intermedias sin usar. |
| **Limpieza general del sistema Docker** | `docker system prune -f` | Elimina contenedores detenidos, redes sin uso y cachés huérfanas. |
| **Reconstrucción limpia sin usar caché** | `docker compose build --no-cache` | Útil si necesitas descargar dependencias completamente desde cero. |

---

## 🌐 6. Acceso a la Aplicación

- **Panel Web:** [http://localhost:5000](http://localhost:5000)
- **Host interno para otros contenedores:** `http://web:5000` o `http://panel_flota_app:5000`
