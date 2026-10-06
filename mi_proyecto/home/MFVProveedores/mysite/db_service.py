import os
import io
import csv
import json
import requests
import openpyxl
from datetime import datetime, timedelta
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session

# --- LÓGICA HORARIA BUENOS AIRES, ARGENTINA (UTC-3) ---
def get_arg_time():
    """Retorna la fecha y hora actual en Argentina (UTC-3)"""
    return datetime.utcnow() - timedelta(hours=3)

def get_hora_full_str():
    return get_arg_time().strftime("%d/%m/%Y %H:%M:%S")

from models import (
    Base, Vehiculo, UnidadContratada, RegistroActividad,
    RegistroCombustible, RegistroFluidos, RegistroMantenimiento,
    RegistroPreventivo, SolicitudRepuesto, CronogramaPreventivo, MetadataSync
)

# Ruta a la base de datos SQLite persistente
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'flota.db')
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# Habilitar WAL (Write-Ahead Logging) en SQLite para máxima concurrencia y velocidad
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

def get_session():
    return SessionLocal()

def init_db():
    """Crea todas las tablas si no existen"""
    Base.metadata.create_all(bind=engine)

# ==============================================================================
# 🔄 MOTOR DE SINCRONIZACIÓN (Google Sheets AUX 2 & AUX 3 -> SQLite)
# ==============================================================================

# Columnas estándar que van a campos directos del modelo Vehiculo
CAMPOS_ESTANDAR = {
    'unidad', 'id', 'tipo', 'marca', 'modelo', 'dominio', 'año', 'ao',
    'área', 'area', 'rea', 'estado', 'diagnóstico', 'diagnostico', 'diagnstico',
    'resumen', 'patrimonio', 'motor', 'chasis', 'chofer', 'legajo', 'dni',
    'foto', 'foto_url', 'nfc_key', 'fecha_alta', 'ex'
}

def sincronizar_desde_google_sheets(url_aux2, url_aux3):
    """
    Descarga las hojas AUX 2 (Flota) y AUX 3 (Contratados) de Google Sheets
    y las sincroniza en la base de datos SQLite.
    Empaqueta especificaciones heterogéneas como documento NoSQL (JSON).
    """
    init_db()
    session = get_session()
    ahora_str = get_hora_full_str()

    filas_aux2_count = 0
    filas_aux3_count = 0

    try:
        # 1. SINCRONIZAR AUX 2 (Flota Propia)
        r2 = requests.get(url_aux2, timeout=20)
        r2.encoding = 'utf-8'
        reader2 = csv.DictReader(io.StringIO(r2.text))
        
        for row in reader2:
            # Buscar columna de unidad/id con tolerancia
            col_id = next((k for k in row.keys() if k and k.strip().lower() in ['unidad', 'id']), None)
            if not col_id:
                continue
            
            vid = str(row.get(col_id, '')).strip().upper()
            if not vid or vid in ['NAN', 'NONE', 'NULL', '']:
                continue

            # Identificar columnas con tolerancia
            def get_val(keywords):
                for k in row.keys():
                    if k and any(kw in k.strip().lower() for kw in keywords):
                        v = row.get(k, '')
                        if v is not None:
                            return str(v).strip()
                return ''

            tipo = get_val(['tipo'])
            marca = get_val(['marca'])
            modelo = get_val(['modelo'])
            dominio = get_val(['dominio', 'patente'])
            anio = get_val(['año', 'ao', 'anio'])
            area = get_val(['área', 'area', 'rea']) or 'SIN ÁREA ASIGNADA'
            estado = get_val(['estado']) or 'ACTIVO'

            # REGLA: Las unidades con estado 'Irrecuperable' están en trámite de baja y NO deben considerarse
            if 'irrecuperable' in estado.lower():
                vehiculo_existente = session.query(Vehiculo).filter_by(id=vid).first()
                if vehiculo_existente:
                    session.delete(vehiculo_existente)
                continue
            diagnostico = get_val(['diagnóstico', 'diagnostico', 'diagnstico'])
            resumen = get_val(['resumen'])
            patrimonio = get_val(['patrimonio'])
            motor = get_val(['motor'])
            chasis = get_val(['chasis'])
            chofer = get_val(['chofer'])
            legajo = get_val(['legajo'])
            dni = get_val(['dni'])
            foto_url = get_val(['foto', 'foto_url'])
            nfc_key = get_val(['nfc_key', 'nfc'])
            fecha_alta = get_val(['fecha_alta'])

            # 2. ESPECIFICACIONES TÉCNICAS (Modelo NoSQL / Documento JSON)
            # Solo guardamos atributos con valor que NO sean los estándar
            especificaciones = {}
            for col_name, col_val in row.items():
                if not col_name:
                    continue
                col_clean = col_name.strip()
                col_lower = col_clean.lower()
                
                # Descartar si es un campo estándar o columna auxiliar interna de compras/costos
                CAMPOS_IGNORAR = [
                    'sum', 'oc', 'fct', 'sos', 'costo', 'presupu', 'prov', 'fec_gest',
                    'nota', 'estado-chofer', 'cant_d', 'cant_t', 'neumaticos_d', 'neumaticos_t'
                ]
                if col_lower in CAMPOS_ESTANDAR or any(kw in col_lower for kw in CAMPOS_IGNORAR):
                    continue

                if col_val is not None:
                    val_str = str(col_val).strip()
                    # Si tiene un valor real (no vacío ni placeholder '-'), se guarda en el JSON
                    if val_str and val_str not in ['-', 'NAN', 'None', 'null']:
                        col_display = col_clean.replace('\ufffd', 'I').replace('', 'I').strip()
                        col_upper_norm = col_clean.upper().replace('Á', 'A').replace('É', 'E').replace('Í', 'I').replace('Ó', 'O').replace('Ú', 'U').replace('\ufffd', 'I').replace('', 'I')

                        nombres_legibles = {
                            'CANT_DELANTERAS': 'Cantidad Neumáticos Delanteros',
                            'NEUMATICOS_DELANTEROS': 'Medida Neumáticos Delanteros',
                            'CANT_TRASERAS': 'Cantidad Neumáticos Traseros',
                            'NEUMATICOS_TRASEROS': 'Medida Neumáticos Traseros',
                            'BATERIAS (CANT)': 'Cantidad de Baterías',
                            'BATERIAS': 'Cantidad de Baterías',
                            'CAPACIDADES': 'Capacidad de Carga / Balde',
                            'ALTURA MAXIMA DE BRAZO HIDROELEVADOR': 'Altura Máxima de Brazo',
                            'POTENCIA [CV]': 'Potencia (CV)',
                            'NEUMATICOS': 'Neumáticos'
                        }
                        display_final = nombres_legibles.get(col_upper_norm, col_display)
                        especificaciones[display_final] = val_str

            # Upsert en la base de datos
            vehiculo = session.query(Vehiculo).filter_by(id=vid).first()
            if not vehiculo:
                vehiculo = Vehiculo(id=vid)
                session.add(vehiculo)

            vehiculo.tipo = tipo.upper() if tipo else vehiculo.tipo
            vehiculo.marca = marca.upper() if marca else vehiculo.marca
            vehiculo.modelo = modelo.upper() if modelo else vehiculo.modelo
            vehiculo.dominio = dominio.upper() if dominio else vehiculo.dominio
            vehiculo.anio = anio
            vehiculo.area = area.upper() if area else vehiculo.area
            vehiculo.estado = estado.upper() if estado else vehiculo.estado
            vehiculo.diagnostico = diagnostico
            vehiculo.resumen = resumen
            vehiculo.patrimonio = patrimonio
            vehiculo.motor = motor
            vehiculo.chasis = chasis
            vehiculo.chofer = chofer
            vehiculo.legajo = legajo
            vehiculo.dni = dni
            if foto_url and foto_url.startswith('http'):
                vehiculo.foto_url = foto_url
            if nfc_key:
                vehiculo.nfc_key = nfc_key
            if fecha_alta:
                vehiculo.fecha_alta = fecha_alta
            
            vehiculo.especificaciones = especificaciones
            vehiculo.actualizado_en = datetime.utcnow()
            filas_aux2_count += 1

        # 3. SINCRONIZAR AUX 3 (Contratados)
        r3 = requests.get(url_aux3, timeout=20)
        r3.encoding = 'utf-8'
        reader3 = csv.DictReader(io.StringIO(r3.text))
        
        # Limpiar tabla de contratados y recargar
        session.query(UnidadContratada).delete()

        for row3 in reader3:
            def get_val3(keywords):
                for k in row3.keys():
                    if k and any(kw in k.strip().lower() for kw in keywords):
                        v = row3.get(k, '')
                        if v is not None:
                            return str(v).strip()
                return ''

            tipo_c = get_val3(['tipo'])
            area_c = get_val3(['area_c', 'área_c', 'area', 'área'])
            cant_c_raw = get_val3(['cantidad_c', 'cant_c', 'cantidad'])
            solo_em_raw = get_val3(['emerg', 'solo_emergencia'])
            de_prest_raw = get_val3(['prestamo', 'de_prestamo'])
            cant_p_raw = get_val3(['cantidad_p', 'cant_p'])

            if not tipo_c or not area_c or tipo_c in ['NAN', 'None', '']:
                continue

            try: cant_c = int(float(cant_c_raw))
            except: cant_c = 1

            try: cant_p = int(float(cant_p_raw))
            except: cant_p = 0

            solo_em = 'SI' in solo_em_raw.upper()

            contratado = UnidadContratada(
                tipo_c=tipo_c.upper(),
                area_c=area_c.upper(),
                cantidad_c=cant_c,
                solo_emergencia=solo_em,
                de_prestamo=de_prest_raw.upper() if de_prest_raw else '',
                cantidad_p=cant_p
            )
            session.add(contratado)
            filas_aux3_count += 1

        # 4. ACTUALIZAR METADATOS DE SYNC
        meta = session.query(MetadataSync).filter_by(id=1).first()
        if not meta:
            meta = MetadataSync(id=1)
            session.add(meta)

        meta.ultima_sincronizacion = ahora_str
        meta.filas_aux2 = filas_aux2_count
        meta.filas_aux3 = filas_aux3_count
        meta.estado_sync = 'OK'
        meta.mensaje = f"Sincronización exitosa: {filas_aux2_count} unidades propias y {filas_aux3_count} contratadas."

        session.commit()
        return {
            'success': True,
            'fecha': ahora_str,
            'filas_aux2': filas_aux2_count,
            'filas_aux3': filas_aux3_count,
            'mensaje': meta.mensaje
        }

    except Exception as e:
        session.rollback()
        print(f"Error sincronizando con Google Sheets: {e}")
        meta = session.query(MetadataSync).filter_by(id=1).first()
        if meta:
            meta.estado_sync = 'ERROR'
            meta.mensaje = str(e)
            session.commit()
        return {'success': False, 'error': str(e)}
    finally:
        session.close()

def seed_if_empty(url_aux2, url_aux3):
    """Verifica si la base de datos está vacía; si lo está, sincroniza automáticamente"""
    init_db()
    session = get_session()
    try:
        count = session.query(Vehiculo).count()
        if count == 0:
            print("Base de datos vacía. Iniciando primera sincronización desde Google Sheets...")
            sincronizar_desde_google_sheets(url_aux2, url_aux3)
    finally:
        session.close()

# ==============================================================================
# 🔍 CONSULTAS RÁPIDAS PARA LA WEB (Lectura de SQLite)
# ==============================================================================

def get_fleet_data():
    """Retorna lista de diccionarios con toda la flota propia activa o en taller (excluye irrecuperables en trámite de baja)"""
    session = get_session()
    try:
        unidades = session.query(Vehiculo).filter(~Vehiculo.estado.ilike('%irrecuperable%')).order_by(Vehiculo.id).all()
        return [u.to_dict() for u in unidades]
    finally:
        session.close()

def find_vehicle_by_id(id_vehiculo):
    """Busca una unidad por su ID/Unidad (ej: 'AE-1')"""
    session = get_session()
    try:
        v = session.query(Vehiculo).filter_by(id=id_vehiculo).first()
        return v.to_dict() if v else None
    finally:
        session.close()

def find_vehicle_by_key(key):
    """Busca una unidad por su llave NFC"""
    if not key:
        return None
    key_clean = key.strip().upper()
    session = get_session()
    try:
        v = session.query(Vehiculo).filter(Vehiculo.nfc_key == key_clean).first()
        return v.to_dict() if v else None
    finally:
        session.close()

def get_status_repuesto(id_vehiculo):
    """Retorna la última solicitud de repuesto activa o estado de inactividad"""
    session = get_session()
    try:
        rep = session.query(SolicitudRepuesto).filter_by(vehiculo_id=id_vehiculo).order_by(SolicitudRepuesto.id.desc()).first()
        return rep.to_dict() if rep else None
    finally:
        session.close()

def update_status_repuesto(id_vehiculo, nuevo_estado, nota="", tipo_registro="REPUESTO", fecha_str=""):
    """Actualiza o crea una solicitud de repuesto / motivo de inactividad"""
    session = get_session()
    try:
        if not fecha_str:
            fecha_str = datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S")

        if nuevo_estado is None:
            # Eliminar solicitudes activas
            session.query(SolicitudRepuesto).filter_by(vehiculo_id=id_vehiculo).delete()
        else:
            rep = session.query(SolicitudRepuesto).filter_by(vehiculo_id=id_vehiculo).first()
            if not rep:
                rep = SolicitudRepuesto(vehiculo_id=id_vehiculo)
                session.add(rep)
            rep.estado = nuevo_estado
            rep.nota = nota
            rep.tipo_registro = tipo_registro
            rep.fecha_update = fecha_str
        
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"Error actualizando repuesto: {e}")
    finally:
        session.close()

def get_cronograma(id_vehiculo):
    session = get_session()
    try:
        c = session.query(CronogramaPreventivo).filter_by(vehiculo_id=id_vehiculo).order_by(CronogramaPreventivo.id.desc()).first()
        return c.to_dict() if c else None
    finally:
        session.close()

def get_all_cronogramas():
    session = get_session()
    try:
        crono = session.query(CronogramaPreventivo).all()
        agenda = []
        for c in crono:
            veh = session.query(Vehiculo).filter_by(id=c.vehiculo_id).first()
            cd = c.to_dict()
            if veh:
                cd['MARCA'] = veh.marca
                cd['MODELO'] = veh.modelo
            agenda.append(cd)
        return agenda
    finally:
        session.close()

# ==============================================================================
# 📝 REGISTRO DE OPERACIONES Y HISTORIALES (Reemplaza CSVs locales)
# ==============================================================================

def record_activity(fecha, vehiculo_id, accion, motivo, responsable="Supervisor Puerta"):
    session = get_session()
    try:
        rec = RegistroActividad(fecha=fecha, vehiculo_id=vehiculo_id, accion=accion, motivo=motivo, responsable=responsable)
        session.add(rec)
        session.commit()
    finally:
        session.close()

def record_fuel(fecha, vehiculo_id, tipo, litros, km):
    session = get_session()
    try:
        l = float(litros) if litros else 0.0
        k = float(km) if km else 0.0
        rec = RegistroCombustible(fecha=fecha, vehiculo_id=vehiculo_id, tipo=tipo, litros=l, km=k)
        session.add(rec)
        session.commit()
    finally:
        session.close()

def record_fluids(fecha, vehiculo_id, categoria, subtipo, cantidad):
    session = get_session()
    try:
        c = float(cantidad) if cantidad else 0.0
        rec = RegistroFluidos(fecha=fecha, vehiculo_id=vehiculo_id, categoria=categoria, subtipo=subtipo, cantidad=c)
        session.add(rec)
        session.commit()
    finally:
        session.close()

def record_maintenance(fecha, vehiculo_id, tipo, detalle):
    session = get_session()
    try:
        rec = RegistroMantenimiento(fecha=fecha, vehiculo_id=vehiculo_id, tipo=tipo, detalle=detalle)
        session.add(rec)
        session.commit()
    finally:
        session.close()

def record_preventive(fecha, vehiculo_id, tipo, responsable, detalle):
    session = get_session()
    try:
        rec = RegistroPreventivo(fecha=fecha, vehiculo_id=vehiculo_id, tipo=tipo, responsable=responsable, detalle=detalle)
        session.add(rec)
        session.commit()
    finally:
        session.close()

def get_history_records(tipo, vehiculo_id):
    """Devuelve la lista de registros para un vehículo y tipo de historial específico"""
    session = get_session()
    try:
        t = tipo.lower()
        if t in ['ingresos', 'actividad']:
            q = session.query(RegistroActividad).filter_by(vehiculo_id=vehiculo_id).order_by(RegistroActividad.id.desc()).all()
        elif t in ['combustible']:
            q = session.query(RegistroCombustible).filter_by(vehiculo_id=vehiculo_id).order_by(RegistroCombustible.id.desc()).all()
        elif t in ['fluidos']:
            q = session.query(RegistroFluidos).filter_by(vehiculo_id=vehiculo_id).order_by(RegistroFluidos.id.desc()).all()
        elif t in ['mantenimiento', 'reparaciones']:
            q = session.query(RegistroMantenimiento).filter_by(vehiculo_id=vehiculo_id).order_by(RegistroMantenimiento.id.desc()).all()
        elif t in ['preventivos', 'cronograma']:
            q = session.query(RegistroPreventivo).filter_by(vehiculo_id=vehiculo_id).order_by(RegistroPreventivo.id.desc()).all()
        else:
            q = []
        return [r.to_dict() for r in q]
    finally:
        session.close()

# ==============================================================================
# 📊 GENERADOR DE DATOS PARA INFORME DE ÁRBOL (/informe/arbol)
# ==============================================================================

def get_tree_report_data():
    """Genera las listas unificadas para el Diagrama de Árbol leyendo de SQLite"""
    session = get_session()
    try:
        vehiculos = session.query(Vehiculo).all()
        contratados = session.query(UnidadContratada).all()

        unidades_lista = []

        # 1. Procesar flota propia (discriminando irrecuperables)
        for v in vehiculos:
            est_raw = (v.estado or '').strip()
            if 'irrecuperable' in est_raw.lower():
                continue

            # Clasificar estado
            est_clean = est_raw.lower()
            if est_clean.startswith('funcional') or 'inactiv' in est_clean or 'reparaci' in est_clean:
                est_cat = 'INACTIVAS'
            elif 'activ' in est_clean:
                est_cat = 'ACTIVAS'
            else:
                est_cat = 'INACTIVAS'

            is_prestamo = 'PRÉSTAMO' in est_raw.upper() or 'PRESTAMO' in est_raw.upper()
            area_origen = (v.area or 'SIN ÁREA ASIGNADA').upper()

            if is_prestamo:
                est_upper = est_raw.upper()
                if ' EN ' in est_upper:
                    dest_part = est_upper.split(' EN ', 1)[1].strip()
                    if 'ALLAN' in dest_part: area_destino = 'DELEGACIÓN ING. ALLAN'
                    elif 'BOSQUES' in dest_part: area_destino = 'DELEGACIÓN BOSQUES'
                    elif 'EQUIPOS VIALES' in dest_part: area_destino = 'EQUIPOS VIALES'
                    elif 'HIGIENE URBANA' in dest_part: area_destino = 'HIGIENE URBANA'
                    elif 'ESPACIOS VERDES' in dest_part: area_destino = 'ESPACIOS VERDES'
                    elif 'CEMENTERIO' in dest_part: area_destino = 'CEMENTERIO'
                    elif 'ALUMBRADO' in dest_part: area_destino = 'ALUMBRADO'
                    else: area_destino = dest_part
                else:
                    area_destino = area_origen
                resumen_norm = f"de {area_origen}"
            else:
                area_destino = area_origen
                resumen_norm = v.resumen or v.diagnostico or 'Sin resumen especificado'

            unidades_lista.append({
                'UNIDAD': v.id,
                'TIPO': (v.tipo or 'SIN TIPO').upper(),
                'AREA': area_destino,
                'AREA_ORIGEN': area_origen,
                'ESTADO_CAT': est_cat,
                'RESUMEN': resumen_norm,
                'CONTRATADO': False,
                'PRESTAMO': is_prestamo
            })

        # 2. Procesar flota contratada (AUX 3)
        for c in contratados:
            tipo_c = c.tipo_c.upper()
            area_c = c.area_c.upper()
            cant_c = c.cantidad_c or 1
            cant_p = c.cantidad_p or 0
            area_p = c.de_prestamo.upper() if c.de_prestamo else None
            resumen_c = "Unidad Contratada (Solo Emergencia)" if c.solo_emergencia else "Unidad Contratada"

            if area_p and cant_p > 0:
                cant_p = min(cant_p, cant_c)
                cant_propias = cant_c - cant_p
            else:
                cant_p = 0
                cant_propias = cant_c

            for i in range(cant_propias):
                unidades_lista.append({
                    'UNIDAD': f"CONTRATADO #{i+1}" if cant_propias > 1 else "CONTRATADO",
                    'TIPO': tipo_c,
                    'AREA': area_c,
                    'AREA_ORIGEN': area_c,
                    'ESTADO_CAT': 'ACTIVAS',
                    'RESUMEN': resumen_c,
                    'CONTRATADO': True,
                    'PRESTAMO': False
                })

            for i in range(cant_p):
                unidades_lista.append({
                    'UNIDAD': f"CONTRATADO #{i+1}" if cant_p > 1 else "CONTRATADO",
                    'TIPO': tipo_c,
                    'AREA': area_p,
                    'AREA_ORIGEN': area_c,
                    'ESTADO_CAT': 'ACTIVAS',
                    'RESUMEN': f"de {area_c}",
                    'CONTRATADO': True,
                    'PRESTAMO': True
                })

        tipos_disponibles = sorted(list(set(u['TIPO'] for u in unidades_lista if u['TIPO'])))
        areas_disponibles = sorted(list(set(u['AREA'] for u in unidades_lista if u['AREA'] and u['AREA'] != 'SIN ÁREA ASIGNADA')))
        if any(u['AREA'] == 'SIN ÁREA ASIGNADA' for u in unidades_lista):
            areas_disponibles.append('SIN ÁREA ASIGNADA')

        return unidades_lista, areas_disponibles, tipos_disponibles
    finally:
        session.close()

# ==============================================================================
# 📑 GESTIÓN DE PLANILLA PROPIA Y EDICIÓN EN LÍNEA (/admin/planilla)
# ==============================================================================

def update_vehicle_cell(vehiculo_id, campo, valor):
    """Actualiza un campo específico de una unidad desde la grilla editable web"""
    session = get_session()
    try:
        v = session.query(Vehiculo).filter_by(id=vehiculo_id).first()
        if not v:
            return {'success': False, 'error': f'Unidad {vehiculo_id} no encontrada'}

        campo_norm = campo.lower().strip()
        val_str = str(valor).strip() if valor is not None else ''

        if campo_norm in ['dominio', 'patente']:
            return {'success': False, 'error': 'El dominio o patente no es editable'}
        elif campo_norm in ['estado']:
            v.estado = val_str.upper()
        elif campo_norm in ['diagnostico', 'diagnóstico']:
            v.diagnostico = val_str
        elif campo_norm in ['resumen']:
            v.resumen = val_str
        elif campo_norm in ['area', 'área']:
            v.area = val_str.upper()
        elif campo_norm in ['chofer']:
            v.chofer = val_str
        elif campo_norm in ['tipo']:
            v.tipo = val_str.upper()
        elif campo_norm in ['motor']:
            v.motor = val_str
        elif campo_norm in ['chasis']:
            v.chasis = val_str
        else:
            # Si es una especificación técnica dinámica NoSQL
            esp = dict(v.especificaciones or {})
            if val_str:
                esp[campo] = val_str
            else:
                esp.pop(campo, None)
            v.especificaciones = esp

        v.actualizado_en = datetime.utcnow()
        session.commit()
        return {'success': True, 'id': vehiculo_id, 'campo': campo, 'valor': val_str}
    except Exception as e:
        session.rollback()
        return {'success': False, 'error': str(e)}
    finally:
        session.close()

def export_fleet_to_excel():
    """Genera un archivo Excel (.xlsx) en memoria con la flota completa formateada (excluye irrecuperables)"""
    session = get_session()
    try:
        vehiculos = session.query(Vehiculo).filter(~Vehiculo.estado.ilike('%irrecuperable%')).order_by(Vehiculo.id).all()
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Flota Municipal"

        # Cabeceras
        headers = [
            "UNIDAD", "TIPO", "MARCA", "MODELO", "DOMINIO", "AÑO", "ÁREA",
            "ESTADO", "DIAGNÓSTICO", "RESUMEN", "PATRIMONIO", "MOTOR",
            "CHASIS", "CHOFER", "ESPECIFICACIONES TÉCNICAS"
        ]
        ws.append(headers)

        for v in vehiculos:
            specs_str = ", ".join([f"{k}: {val}" for k, val in (v.especificaciones or {}).items()])
            row = [
                v.id, v.tipo, v.marca, v.modelo, v.dominio, v.anio, v.area,
                v.estado, v.diagnostico, v.resumen, v.patrimonio, v.motor,
                v.chasis, v.chofer, specs_str
            ]
            ws.append(row)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output
    finally:
        session.close()

def get_sync_status():
    """Retorna la fecha y estado del último sync con Google Sheets"""
    session = get_session()
    try:
        meta = session.query(MetadataSync).filter_by(id=1).first()
        if meta:
            return {
                'ultima_sincronizacion': meta.ultima_sincronizacion,
                'filas_aux2': meta.filas_aux2,
                'filas_aux3': meta.filas_aux3,
                'estado': meta.estado_sync,
                'mensaje': meta.mensaje
            }
        return {'ultima_sincronizacion': 'Pendiente', 'estado': 'PENDIENTE'}
    finally:
        session.close()
