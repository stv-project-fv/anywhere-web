---
name: flota-verificacion
description: >-
  Ejecuta la suite de pruebas de integración y auditoría adversarial del proyecto Panel Flota
  sobre una copia temporal aislada de SQLite (FLOTA_DB_PATH), verificando que flota.db no sufra
  modificaciones, que PRAGMA integrity_check sea ok y que las 4 rutas protegidas de /historial/*
  respondan HTTP 200. Usar siempre antes de dar por finalizada cualquier modificación de código.
---

# Verificación Aislada e Integridad SQLite (`flota-verificacion`)

Esta skill garantiza que todos los cambios en `flask_app.py`, `db_service.py`, `models.py` o `templates/` pasen el 100% de las pruebas funcionales y adversariales **sin tocar ni mutar la base de datos local `flota.db`**.

## Procedimiento de Ejecución

1. **Ejecutar el runner de verificación aislada** desde la raíz del repositorio:
   ```powershell
   python .agents/skills/flota-verificacion/scripts/run_isolated_tests.py
   ```
   *(El script [run_isolated_tests.py](./scripts/run_isolated_tests.py) toma el hash SHA-256 inicial de `flota.db`, crea un clon temporal con la API nativa de backup de SQLite, inyecta `FLOTA_DB_PATH`, corre los 10 bloques de `test_integration.py` más los 10 chequeos adversariales de contrato, elimina el clon temporal y comprueba que el hash SHA-256 final de `flota.db` sea idéntico al inicial).*

2. **Alternativa de ejecución directa de `test_integration.py`**:
   ```powershell
   python mi_proyecto/home/MFVProveedores/mysite/test_integration.py
   ```
   `test_integration.py` también crea automáticamente su propio clon temporal si `FLOTA_DB_PATH` no está definido en el entorno.

## Criterios de Aceptación Obligatorios

- **Exit code `0`** en la ejecución del script.
- **Invarianza de `flota.db`**: El hash SHA-256 de `mi_proyecto/home/MFVProveedores/mysite/flota.db` antes y después del test debe coincidir exactamente.
- **Salud de SQLite**:
  - `PRAGMA integrity_check` retorna `[('ok',)]`.
  - `PRAGMA foreign_key_check` retorna `[]`.
- **4 Rutas de Historial Protegidas Operativas**:
  - `/historial/mantenimiento/AE-1` -> HTTP 200
  - `/historial/imagenes/AE-1` -> HTTP 200
  - `/historial/ingresos/AE-1` -> HTTP 200
  - `/historial/cronograma/AE-1` -> HTTP 200
- **Rutas Obsoletas de Kiosco Desmanteladas**:
  - `/puesto/actividad`, `/operacion/actividad/AE-1` y `/taller/mecanico` -> HTTP 404.

