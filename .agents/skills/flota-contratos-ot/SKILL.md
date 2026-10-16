---
name: flota-contratos-ot
description: >-
  Referencia técnica de contratos Frontend-Backend, esquemas de serialización to_dict(),
  enrutamiento de columnas SQL vs JSON en update_vehicle_cell, aislamiento de paneles de taller
  (/taller vs /admin/taller), escape de comillas en modales Jinja2 y flujo de Órdenes de Trabajo (OT).
  Usar al modificar flask_app.py, db_service.py, models.py o plantillas en templates/.
---

# Contratos Frontend-Backend y Órdenes de Trabajo (`flota-contratos-ot`)

Esta skill consolida los contratos verificados entre `models.py`, `db_service.py`, `flask_app.py` y las plantillas Jinja2/Tabulator en `templates/`.

---

## 1. Simetría de Diccionarios (`to_dict()`)

El proyecto mantiene dos convenciones de nombres de claves según la familia de modelos:

1. **Modelos de Flota e Historiales Base (`Vehiculo`, `UnidadContratada`, `Registro*`, `SolicitudRepuesto`, `CronogramaPreventivo`)**:
   - Retornan claves en **MAYÚSCULAS**.
   - `Vehiculo.to_dict()` **debe** incluir siempre alias simétricos con y sin tilde para evitar fallos entre plantillas y clientes JSON:
     - `'AÑO'` y `'ANIO'`
     - `'ÁREA'` y `'AREA'`
     - `'DIAGNÓSTICO'` y `'DIAGNOSTICO'`
     - `'ID'` y `'UNIDAD'`
   - Además, `Vehiculo.to_dict()` desglosa en el primer nivel las claves dinámicas almacenadas en `self.especificaciones` (sin pisar las claves estructurales).

2. **Modelos de Taller y Sincronización (`OrdenTrabajo`, `AvanceOT`, `RepuestoOT`, `MetadataSync`)**:
   - Retornan claves en **`snake_case` (minúsculas)**:
     - `OrdenTrabajo.to_dict()`: `id`, `numero_ot`, `vehiculo_id`, `fecha_ingreso`, `fecha_egreso`, `estado_ot`, `prioridad`, `sistema_afectado`, `mecanico_asignado`, `motivo_ingreso`, `trabajo_realizado`, `repuestos_detalle`, `km_ingreso`, `km_egreso`, `inmoviliza_unidad`.
     - `MetadataSync.to_dict()`: incluye tanto `'estado_sync'` como `'estado'` por compatibilidad.

3. **Contrato Enriquecido de OT (`get_ot_by_id`, `get_ot_activa_vehiculo`, `get_ordenes_taller_activas`)**:
   - Todo diccionario de OT retornado a las vistas debe enriquecerse con:
     - Metadatos del vehículo: `marca`, `modelo`, `dominio`, `area`, `foto_url`, `tipo_vehiculo`.
     - Cálculo de días en taller: `dias_en_taller` (entero `>= 0` calculado con `get_arg_time().date()`).
     - Listas anidadas: `avances` y `repuestos`.

---

## 2. Contrato de Edición en Vivo (`/api/vehiculo/actualizar` -> `update_vehicle_cell`)

- **Campos bloqueados (inmutables)**:
  - `dominio`, `patente` ➔ `{'success': False, 'error': 'El dominio o patente no es editable'}`
  - `id`, `unidad` ➔ `{'success': False, 'error': 'El identificador de la unidad no es editable'}`
- **Columnas estructurales SQL (asignación directa al modelo `Vehiculo`)**:
  - En mayúsculas automáticas (`.upper()`): `estado`, `area`/`área`, `tipo`, `marca`, `modelo`.
  - En texto preservado: `diagnostico`/`diagnóstico`, `resumen`, `chofer`, `motor`, `chasis`, `anio`/`año`/`ao`, `patrimonio`, `legajo`, `dni`, `fecha_alta`, `foto_url`/`foto`.
- **Atributos dinámicos NoSQL (`Vehiculo.especificaciones`)**:
  - Solo los campos que no pertenecen a las listas anteriores se guardan o eliminan dentro del diccionario JSON `v.especificaciones`.

---

## 3. Plantillas Jinja2, Tabulator y Escape JavaScript

1. **Escape obligatorio de comillas simples en eventos `onclick` inline**:
   - En `templates/taller.html` (`abrirModalRecibirRepuesto`) y `templates/admin_taller.html` (`abrirModalTramitar`), las descripciones de repuestos suelen incluir medidas en pulgadas o apóstrofes (ej. `O'ring`, `1/2'`).
   - Siempre interpolar usando `{{ r.descripcion|replace("'", "\\'") }}`.

2. **Selector de `ESTADO` en Tabulator (`templates/admin_planilla.html`)**:
   - Cuando se abre una OT en taller, `crear_orden_trabajo` asigna `v.estado = 'EN REPARACIÓN'` (con tilde).
   - El `editorParams.values` de la columna `ESTADO` en `admin_planilla.html` debe mantener `"EN REPARACIÓN"` para coincidir con el estado real del backend.

3. **Aislamiento de Navegación entre Paneles**:
   - `templates/taller.html`: Uso exclusivo de operarios de galpón. **Prohibido** agregar botones o enlaces hacia `/admin/taller` o `/`.
   - `templates/admin_taller.html`: Uso administrativo y compras. Conserva enlace hacia `/`, pero **prohibido** agregar enlaces hacia `/taller`.

4. **Prevención de Duplicados en `/historial/mantenimiento/<id>`**:
   - `cerrar_orden_trabajo` no debe insertar registros redundantes en `RegistroMantenimiento`.
   - `get_history_records('mantenimiento', id)` ignora cualquier fila histórica en `RegistroMantenimiento` cuyo `detalle` comience con `'OT #'`.

