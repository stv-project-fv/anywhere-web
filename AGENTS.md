# AGENTS.md — Panel Flota Municipal

Instrucciones operativas persistentes para agentes en Google Antigravity (Gemini 4 Argon). Este archivo en la raíz del repositorio se carga automáticamente para todo el proyecto.

---

## 1. Principios No Negociables

1. **Cero invención**: Nunca inventar rutas de archivos, endpoints, nombres de columnas, esquemas JSON ni resultados de pruebas. Si hay duda, leer el código o consultar al usuario.
2. **Cambios quirúrgicos y mínimos**: Cada línea modificada debe responder directamente al pedido del usuario. No realizar refactorizaciones colaterales ni agregar abstracciones especulativas.
3. **Comunicación directa y concisa**: Sin rellenos ni fórmulas de cortesía innecesarias. Explicar decisiones técnicas con enlaces a archivos y líneas exactas.
4. **Verificación obligatoria y aislada**: Ningún cambio de código se da por finalizado sin ejecutar la verificación automatizada sobre una **copia temporal aislada** de SQLite (`FLOTA_DB_PATH`), garantizando cero alteraciones en `flota.db`.

---

## 2. Compuertas de Aprobación Humana (Human-in-the-Loop)

Detenerse y solicitar aprobación explícita del usuario (mediante `/plan` o `ask_question`) **antes** de:
- Modificar el esquema relacional en `mi_proyecto/home/MFVProveedores/mysite/models.py` o ejecutar migraciones/alteraciones directas sobre `flota.db`.
- Alterar cualquiera de las **4 rutas protegidas de historial**:
  - `/historial/mantenimiento/<id>`
  - `/historial/imagenes/<id>`
  - `/historial/ingresos/<id>`
  - `/historial/cronograma/<id>`
- Modificar `Dockerfile`, `docker-compose.yml`, `requirements.txt` o variables de entorno (`.env` / `.env.example`).
- Disparar sincronizaciones contra Google Sheets (`/api/sincronizar_sheets` o `sincronizar_desde_google_sheets`) o comandos destructivos de Docker/Git.

---

## 3. Orquestación Híbrida: Trabajo Paralelo vs. Secuencial

- **Cuándo usar paralelismo (`invoke_subagent` con `TypeName="research"`, `Model="inherit"`)**:
  - Auditorías de solo lectura divididas por capa:
    - *Rol Auditor Frontend*: inspección de plantillas Jinja2 (`templates/`), grillas Tabulator y llamadas `fetch`/JS inline.
    - *Rol Auditor Backend*: inspección de rutas en `flask_app.py`, lógica en `db_service.py` y modelos en `models.py`.
  - Nunca lanzar subagentes paralelos que escriban en los mismos archivos o que ejecuten pruebas sobre el mismo archivo SQLite.
- **Cuándo usar ejecución secuencial**:
  - Aplicación de cambios de código que vinculan contratos entre Backend (`db_service.py` / `flask_app.py`) y Frontend (`templates/*.html`).
  - Ejecución de pruebas de integración y validación de integridad SQLite.

---

## 4. Arquitectura y Mapa del Proyecto

- **Código fuente (`mi_proyecto/home/MFVProveedores/mysite/`)**:
  - `flask_app.py`: Controladores Flask, rutas web, inyección de contexto y endpoints REST (`/api/vehiculo/actualizar`, `/api/sincronizar_sheets`, `/admin/exportar/excel`).
  - `models.py`: Modelos declarativos SQLAlchemy 2.0 (`Vehiculo`, `UnidadContratada`, `OrdenTrabajo`, `AvanceOT`, `RepuestoOT`, `MetadataSync`, `RegistroActividad`, `RegistroCombustible`, `RegistroFluidos`, `RegistroMantenimiento`, `RegistroPreventivo`, `SolicitudRepuesto`, `CronogramaPreventivo`).
  - `db_service.py`: Capa de acceso a datos SQLite, gestión de sesiones, ciclo de vida de OTs, sincronización Google Sheets y exportación Excel.
  - `flota.db`: Base de datos SQLite activa de producción local (**zona protegida**; configurable para tests mediante la variable de entorno `FLOTA_DB_PATH`).
  - `templates/`: Vistas Jinja2 (`index.html`, `taller.html`, `admin_taller.html`, `admin_planilla.html`, `ficha.html`, `historial.html`, `informe_arbol.html`, `recortar.html`, `mapa_sitio.html`).
  - `test_integration.py`: Suite de integración (10 bloques de verificación; clona `flota.db` a un archivo temporal aislado automáticamente).

---

## 5. Reglas de Negocio e Invariantes del Dominio

1. **Zona Horaria Oficial Argentina (UTC-3)**:
   - Usar siempre `get_arg_time()` o `get_hora_full_str()` (`%d/%m/%Y %H:%M:%S`) para todo sello temporal de negocio (aperturas/cierres de OT, avances, solicitudes/trámites/recepciones de repuestos y sincronizaciones).
2. **Gestión de Sesiones SQLite**:
   - Toda función en `db_service.py` que invoque `session = get_session()` debe cerrar la sesión en un bloque `try: ... finally: session.close()`.
3. **Inmutabilidad de Identificadores**:
   - En `update_vehicle_cell` (`/api/vehiculo/actualizar`), los campos `id`, `unidad`, `dominio` y `patente` están bloqueados y deben retornar `{'success': False, 'error': ...}`.
   - Las columnas estructurales (`marca`, `modelo`, `anio`/`año`/`ao`, `patrimonio`, `legajo`, `dni`, `fecha_alta`, `foto_url`, `estado`, `diagnostico`, `resumen`, `area`, `chofer`, `tipo`, `motor`, `chasis`) deben asignarse a columnas SQL de `Vehiculo`, nunca al JSON `especificaciones`.
4. **Unidades `'Irrecuperable'`**:
   - Excluir siempre unidades con estado `'Irrecuperable'` (`~Vehiculo.estado.ilike('%irrecuperable%')`) de la flota operativa (`get_fleet_data()`), métricas generales y exportación Excel (`export_fleet_to_excel()`).
   - En `/ficha/<id>`, toda unidad `'irrecuperable'` debe evaluarse como inactiva y renderizar el badge rojo `st-bad`.
5. **Aislamiento de Paneles de Taller y Circuito de Repuestos**:
   - `/taller` (operarios de galpón) está estrictamente aislado: no debe incluir enlaces hacia `/admin/taller` ni hacia `/`.
   - `/admin/taller` (administración y compras) conserva enlace a `/`, pero no debe enlazar a `/taller`.
   - Secuencia de repuestos: `SOLICITADO` (operario en `/taller`) ➔ `EN_TRAMITE` (administrativo con OC/proveedor en `/admin/taller`) ➔ `RECIBIDO` (operario con remito físico en `/taller`).
   - El cierre de OT (`cerrar_orden_trabajo`) devuelve la unidad a `'ACTIVO'` sin insertar filas duplicadas en `RegistroMantenimiento`. Si la OT tiene `sistema_afectado == 'SERVICE'`, registra automáticamente su entrada en `RegistroPreventivo` (`/historial/cronograma/<id>`).
   - Prohibido reintroducir vistas o rutas obsoletas de kioscos/NFC (`/puesto/actividad`, `/operacion/actividad/<id>`, `/taller/mecanico`, `/auditor`, `/auditor/service/<id>`).

---

## 6. Skills del Proyecto (Progressive Disclosure)

Consultar las skills especializadas en `.agents/skills/` según la tarea:
- **`flota-verificacion`** (`.agents/skills/flota-verificacion/SKILL.md`): Ejecución de la suite de pruebas e integridad SQLite en base temporal aislada.
- **`flota-contratos-ot`** (`.agents/skills/flota-contratos-ot/SKILL.md`): Contratos de diccionarios `to_dict()`, Tabulator, escape de comillas en modales JS y flujo de OTs.
- **`flota-docker-deploy`** (`.agents/skills/flota-docker-deploy/SKILL.md`): Comandos Docker seguros, backups atómicos de `flota.db` y despliegue en PythonAnywhere.

