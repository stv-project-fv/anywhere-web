import os
import io
import csv
import json
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv
from PIL import Image
import qrcode
from flask import Flask, render_template, request, send_file, session, redirect, url_for, flash, jsonify
from flask_caching import Cache
import db_service as db

# Cargar variables de entorno desde el archivo .env si existe
base_dir = os.path.dirname(os.path.abspath(__file__))
env_paths = [
    os.path.join(base_dir, '.env'),
    os.path.join(base_dir, '..', '.env'),
    os.path.join(base_dir, '..', '..', '.env'),
    os.path.join(base_dir, '..', '..', '..', '.env'),
    '/home/MFVProveedores/mysite/.env',
    '/home/MFVProveedores/.env'
]
loaded = False
for p in env_paths:
    if os.path.exists(p):
        load_dotenv(p, override=True)
        loaded = True
        break
if not loaded:
    load_dotenv(override=True)

# --- LÓGICA HORARIA ARGENTINA ---
def get_arg_time():
    """Retorna la fecha y hora actual en Argentina (UTC-3)"""
    return datetime.utcnow() - timedelta(hours=3)

def get_fecha_str():
    return get_arg_time().strftime("%d/%m/%Y")

def get_hora_full_str():
    return get_arg_time().strftime("%d/%m/%Y %H:%M:%S")

# ==============================================================================
# ⚙️  CONFIGURACIÓN DEL SISTEMA
# ==============================================================================

CONF = {
    # --- CONEXIÓN DE LECTURA ---
    "URL_FLOTA_PRINCIPAL": os.getenv("URL_FLOTA_PRINCIPAL", "https://docs.google.com/spreadsheets/d/e/2PACX-1vSqdZ6I77VKHqDefS3qrzvVw4LofQ4RLGqsSjs6VVns9P6Esu1Jg0eTRyW0UsW9m1UNrj_lG-VBLKxX/pub?gid=0&single=true&output=csv"),

    # LINKS HISTORIALES (Legacy + Nuevos)
    "URL_HIST_ACTIVIDAD":  os.getenv("URL_HIST_ACTIVIDAD", "https://docs.google.com/spreadsheets/d/e/2PACX-1vT3RNyn_xegGfpnayal7bqN1TN3mjceJk2_jRBD2r2MzKPDr5EheK2e5nxBDQ2Op7aVy0E5jLTRbPOw/pub?gid=0&single=true&output=csv"), # Ahora Ingresos/Egresos

    # Estos se usan internamente pero ya no se muestran en ficha pública
    "URL_HIST_COMBUSTIBLE": os.getenv("URL_HIST_COMBUSTIBLE", "https://docs.google.com/spreadsheets/d/e/2PACX-1vRTPuU9v8Uy9ZKVxiqD70thX_VH7OPLQzcHiGxZegBvzRzFnR4_yde8PB94V5jyAKdIX8xBzEsCxC-e/pub?gid=0&single=true&output=csv"),

    # URLs para el Informe de Árbol
    "URL_INFORME_ARBOL": os.getenv("URL_INFORME_ARBOL", "https://docs.google.com/spreadsheets/d/e/2PACX-1vRU_iWqEQETjf8NcTkqaKsciFQQp7FsEdrdvo-bxH3kN5E87awaHb4oqODO2PgtXN1P5Gl3VGuEtuBl/pub?gid=1643077296&single=true&output=csv"),
    "URL_INFORME_ARBOL_CONTRATADOS": os.getenv("URL_INFORME_ARBOL_CONTRATADOS", "https://docs.google.com/spreadsheets/d/e/2PACX-1vRU_iWqEQETjf8NcTkqaKsciFQQp7FsEdrdvo-bxH3kN5E87awaHb4oqODO2PgtXN1P5Gl3VGuEtuBl/pub?gid=747455468&single=true&output=csv"),

    # Campos
    "CAMPOS_PUBLICOS_BASE": ['ID', 'TIPO', 'MARCA', 'MODELO', 'DOMINIO', 'AÑO', 'ESTADO', 'FOTO_URL', 'AREA', 'FECHA_ALTA', 'NFC_KEY'],
    "CAMPOS_PRIVADOS":      ['MOTOR', 'CHASIS', 'PATRIMONIO', 'CHOFER', 'LEGAJO', 'DNI'],

    # Contraseñas y Seguridad cargadas de variables de entorno (.env)
    "PASSWORD_ADMIN": os.getenv("PASSWORD_ADMIN", "muni2025"),
    "PASSWORD_PANEL": os.getenv("PASSWORD_PANEL", "gpa2025"),
    "SECRET_KEY": os.getenv("SECRET_KEY", "clave_super_zecreta_varela_v13"),

    # --- IMÁGENES Y ESTÉTICA (ARCHIVOS LOCALES) ---
    "LOGO_URL": os.getenv("LOGO_URL", "/static/Logo1.png"),
    "QR_LOGO_URL": os.getenv("QR_LOGO_URL", "/static/Logo-QR.png"),
    "BANNER_PANEL_URL": os.getenv("BANNER_PANEL_URL", "/static/banner-sospapu.png"),
    "BANNER_FICHA_URL": os.getenv("BANNER_FICHA_URL", "/static/banner-sospapu.png"),
    "SIN_FOTO_URL": os.getenv("SIN_FOTO_URL", "/static/Sin-dato-de-imagen.png"),
    "BACKGROUND_URL": os.getenv("BACKGROUND_URL", ""),

    "COLOR_PRINCIPAL": "#009B77",
    "COLOR_SECUNDARIO": "#DAA520",
    "COLOR_ROJO": "#dc3545",
    "COLOR_VERDE": "#28a745",
}

app = Flask(__name__)
app.secret_key = CONF['SECRET_KEY']
cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': 60})

# Inyección global de configuración y funciones a las plantillas Jinja2
@app.context_processor
def inject_globals():
    return {
        'CONF': CONF,
        'get_fecha_str': get_fecha_str,
        'get_hora_full_str': get_hora_full_str
    }

# ==============================================================================
# 🧠  LÓGICA DE DATOS (Persistencia SQLite y Sincronización Google Sheets)
# ==============================================================================

# Inicialización y siembra automática de SQLite si la base está vacía
try:
    db.seed_if_empty(CONF["URL_INFORME_ARBOL"], CONF["URL_INFORME_ARBOL_CONTRATADOS"])
except Exception as e:
    print(f"Aviso al verificar base de datos SQLite: {e}")

def get_fleet_data():
    """Retorna los datos de la flota persistidos en SQLite (lectura instantánea <2ms)"""
    return db.get_fleet_data()

def find_vehicle_by_key(key):
    """Búsqueda optimizada por clave NFC en SQLite"""
    return db.find_vehicle_by_key(key)

def find_vehicle_by_id(id_vehiculo):
    """Búsqueda por ID de unidad en SQLite"""
    return db.find_vehicle_by_id(id_vehiculo)

def calcular_dias_actividad(fecha_alta_str):
    try:
        if not fecha_alta_str: return "Sin dato"
        alta = datetime.strptime(fecha_alta_str, "%d/%m/%Y")
        dias = (get_arg_time() - alta).days
        return f"{dias} días"
    except: return "Sin dato"

# --- LÓGICA DE ESTADOS Y MANTENIMIENTO ---
def get_status_repuesto(id_vehiculo):
    """Lee estado de repuesto O razón de inactividad desde SQLite"""
    return db.get_status_repuesto(id_vehiculo)

def update_status_repuesto(id_vehiculo, nuevo_estado, nota="", tipo_registro="REPUESTO"):
    """
    tipo_registro: 'REPUESTO' (solicitud) o 'INACTIVIDAD' (razón de baja)
    """
    db.update_status_repuesto(id_vehiculo, nuevo_estado, nota=nota, tipo_registro=tipo_registro, fecha_str=get_hora_full_str())

def get_cronograma(id_vehiculo):
    """Obtiene el próximo mantenimiento programado desde SQLite"""
    return db.get_cronograma(id_vehiculo)

# ==============================================================================
# 🚦  RUTAS DEL SISTEMA
# ==============================================================================

@app.route('/icon-muni.ico')
@app.route('/favicon.ico')
def favicon_muni():
    return send_file(os.path.join(os.path.dirname(__file__), 'icon-muni.ico'), mimetype='image/x-icon')

@app.route('/mapa_sitio')
def mapa_sitio():
    lista_rutas = []
    for rule in app.url_map.iter_rules():
        if "static" in rule.rule or "GET" not in rule.methods:
            continue
        es_dinamica = "<" in rule.rule
        metodos = ", ".join([m for m in rule.methods if m not in ['HEAD', 'OPTIONS']])
        lista_rutas.append({
            "endpoint": rule.endpoint,
            "url": rule.rule,
            "methods": metodos,
            "dynamic": es_dinamica
        })

    lista_rutas.sort(key=lambda x: x['url'])
    return render_template('mapa_sitio.html', rutas=lista_rutas)

# --- 1. PANEL DE FLOTA (CON LOGIN) ---
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST' and 'panel_login' in request.form:
        if request.form.get('password') == CONF['PASSWORD_PANEL']:
            session['panel_logged_in'] = True
        else:
            flash("Contraseña incorrecta")

    if not session.get('panel_logged_in'):
        return render_template('login.html')

    datos = get_fleet_data()
    total = len(datos)
    activos = sum(1 for v in datos if 'inactiv' not in v.get('ESTADO','').lower() and 'reparaci' not in v.get('ESTADO','').lower() and 'irrecuperable' not in v.get('ESTADO','').lower())
    inactivos = total - activos
    percent = int((activos / total * 100)) if total else 0
    sync_status = db.get_sync_status()

    return render_template('index.html', datos=datos, total=total, activos=activos, inactivos=inactivos, percent=percent, sync_status=sync_status)

# --- 2. GESTIÓN OPERATIVA DE TALLER (ÓRDENES DE TRABAJO) ---
@app.route('/taller', methods=['GET'])
def taller():
    ots_activas = db.get_ordenes_taller_activas()
    flota = get_fleet_data()
    total_en_taller = len(ots_activas)
    en_reparacion = sum(1 for o in ots_activas if o.get('estado_ot') == 'EN_REPARACION')
    esperando_repuesto = sum(1 for o in ots_activas if o.get('estado_ot') == 'ESPERANDO_REPUESTO')
    urgentes = sum(1 for o in ots_activas if o.get('prioridad') == 'URGENTE')

    return render_template(
        'taller.html',
        ots=ots_activas,
        flota=flota,
        total=total_en_taller,
        en_reparacion=en_reparacion,
        esperando_repuesto=esperando_repuesto,
        urgentes=urgentes
    )

@app.route('/taller/ot/crear', methods=['POST'])
def taller_crear_ot():
    vid = request.form.get('vehiculo_id', '').strip()
    motivo = request.form.get('motivo_ingreso', '').strip()
    sistema = request.form.get('sistema_afectado', 'MECANICA').strip()
    prioridad = request.form.get('prioridad', 'NORMAL').strip()
    mecanico = request.form.get('mecanico_asignado', '').strip()
    km = request.form.get('km_ingreso', '').strip()

    if not vid or not motivo:
        flash("Debe seleccionar un vehículo e ingresar el motivo de la falla.")
        return redirect(url_for('taller'))

    try:
        ot = db.crear_orden_trabajo(
            vehiculo_id=vid,
            motivo_ingreso=motivo,
            sistema_afectado=sistema,
            prioridad=prioridad,
            mecanico_asignado=mecanico,
            km_ingreso=km,
            inmoviliza_unidad=True
        )
        flash(f"Orden de trabajo {ot['numero_ot']} generada con éxito para la unidad {vid}.")
    except Exception as e:
        flash(f"Error al generar orden de trabajo: {e}")

    return redirect(url_for('taller'))

@app.route('/taller/ot/<int:ot_id>/avance', methods=['POST'])
def taller_agregar_avance(ot_id):
    descripcion = request.form.get('descripcion', '').strip()
    mecanico = request.form.get('mecanico', '').strip()

    if not descripcion:
        flash("Debe ingresar la descripción del avance técnico.")
        return redirect(url_for('taller'))

    res = db.agregar_avance_ot(ot_id, descripcion, mecanico)
    if res.get('success'):
        flash("Avance técnico registrado con fecha y hora.")
    else:
        flash(f"Error al registrar avance: {res.get('error')}")

    return redirect(url_for('taller'))

@app.route('/taller/ot/<int:ot_id>/repuesto/solicitar', methods=['POST'])
def taller_solicitar_repuesto(ot_id):
    descripcion = request.form.get('descripcion', '').strip()
    cantidad = request.form.get('cantidad', 1)
    observaciones = request.form.get('observaciones', '').strip()

    if not descripcion:
        flash("Debe especificar la descripción del repuesto requerido.")
        return redirect(url_for('taller'))

    res = db.agregar_repuesto_ot(ot_id, descripcion, cantidad, observaciones)
    if res.get('success'):
        flash(f"Repuesto '{descripcion}' solicitado exitosamente.")
    else:
        flash(f"Error al solicitar repuesto: {res.get('error')}")

    return redirect(url_for('taller'))

@app.route('/taller/repuesto/<int:repuesto_id>/recibir', methods=['POST'])
def taller_recibir_repuesto(repuesto_id):
    remito = request.form.get('remito', '').strip()
    observaciones = request.form.get('observaciones', '').strip()

    res = db.confirmar_recepcion_repuesto(repuesto_id, remito, observaciones)
    if res.get('success'):
        rep = res.get('repuesto', {})
        flash(f"Recepción física del repuesto '{rep.get('descripcion')}' confirmada en taller.")
    else:
        flash(f"Error al confirmar recepción: {res.get('error')}")

    return redirect(url_for('taller'))

@app.route('/taller/ot/<int:ot_id>/cerrar', methods=['POST'])
def taller_cerrar_ot(ot_id):
    trabajo = request.form.get('trabajo_realizado', '').strip()
    km = request.form.get('km_egreso', '').strip()

    res = db.cerrar_orden_trabajo(ot_id, trabajo_realizado=trabajo, km_egreso=km)
    if res.get('success'):
        ot = res.get('ot', {})
        flash(f"Alta operativa otorgada. Unidad {ot.get('vehiculo_id')} reincorporada a la flota activa.")
    else:
        flash(f"Error al cerrar orden: {res.get('error')}")

    return redirect(url_for('taller'))


# --- 3. VISUALIZACIÓN DE HISTORIALES ---
@app.route('/historial/<tipo>/<id_vehiculo>')
def ver_historial(tipo, id_vehiculo):
    config_historial = {
        'ingresos':     {'titulo': 'CONTROL DE INGRESOS'},
        'actividad':    {'titulo': 'CONTROL DE INGRESOS'},
        'cronograma':   {'titulo': 'CRONOGRAMA PREVENTIVO'},
        'preventivos':  {'titulo': 'CRONOGRAMA PREVENTIVO'},
        'mantenimiento':{'titulo': 'HISTORIAL DE REPARACIONES'},
        'reparaciones': {'titulo': 'HISTORIAL DE REPARACIONES'},
        'imagenes':     {'titulo': 'LEGAJO FOTOGRÁFICO'},
        'datos':        {'titulo': 'LEGAJO FOTOGRÁFICO'},
        'combustible':  {'titulo': 'HISTORIAL DE COMBUSTIBLE'},
        'fluidos':      {'titulo': 'HISTORIAL DE FLUIDOS'}
    }

    cfg = config_historial.get(tipo.lower())
    if not cfg:
        return "Tipo de historial no válido", 404

    vehiculo = find_vehicle_by_id(id_vehiculo)
    registros = db.get_history_records(tipo, id_vehiculo)
    columnas = [k for k in registros[0].keys() if k != 'ID'] if registros else []

    return render_template(
        'historial.html',
        tipo=tipo.lower(),
        id_vehiculo=id_vehiculo,
        vehiculo=vehiculo or {},
        titulo=cfg['titulo'],
        registros=registros,
        columnas=columnas
    )

# --- 4. FICHA TÉCNICA ---
@app.route('/ficha/<id_vehiculo>', methods=['GET', 'POST'])
def ficha(id_vehiculo):
    vehiculo = find_vehicle_by_id(id_vehiculo)
    if not vehiculo:
        return "<h1>Unidad no encontrada</h1>", 404

    if request.method == 'POST':
        if request.form.get('password') == CONF['PASSWORD_ADMIN']:
            session['admin_logged_in'] = True

    es_admin = session.get('admin_logged_in', False)
    specs = vehiculo.get('ESPECIFICACIONES', {})
    priv = {k: vehiculo.get(k, '') for k in CONF['CAMPOS_PRIVADOS'] if vehiculo.get(k, '').strip()}

    is_inactive = 'inactiv' in vehiculo.get('ESTADO','').lower() or 'reparaci' in vehiculo.get('ESTADO','').lower()
    est_cls = "st-bad" if is_inactive else "st-ok"
    dias = calcular_dias_actividad(vehiculo.get('FECHA_ALTA', ''))

    razon_inactividad = ""
    if is_inactive:
        status_data = get_status_repuesto(id_vehiculo)
        if status_data and status_data.get('TIPO_REGISTRO') == 'INACTIVIDAD':
            razon_inactividad = status_data.get('NOTA', 'Sin motivo especificado')

    ot_activa = db.get_ot_activa_vehiculo(id_vehiculo)
    historial_ots = db.get_historial_ot_vehiculo(id_vehiculo)

    return render_template(
        'ficha.html',
        v=vehiculo,
        specs=specs,
        priv=priv,
        admin=es_admin,
        est_cls=est_cls,
        dias=dias,
        razon_inactiva=razon_inactividad,
        ot_activa=ot_activa,
        historial_ots=historial_ots
    )

@app.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    return redirect(request.referrer or url_for('index'))

@app.route('/qr/<id_vehiculo>')
def generate_qr(id_vehiculo):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=15,
        border=2
    )
    qr.add_data(f"{request.host_url}ficha/{id_vehiculo}")
    qr.make(fit=True)

    qr_img = qr.make_image(fill_color=CONF['COLOR_PRINCIPAL'], back_color="white").convert('RGBA')

    try:
        qr_logo_val = CONF.get('QR_LOGO_URL', '/static/Logo-QR.png')
        if qr_logo_val.startswith('http://') or qr_logo_val.startswith('https://'):
            response = requests.get(qr_logo_val, stream=True)
            response.raw.decode_content = True
            logo_img = Image.open(response.raw).convert("RGBA")
        else:
            clean_name = os.path.basename(qr_logo_val)
            static_path = os.path.join(os.path.dirname(__file__), 'static', clean_name)
            if os.path.exists(static_path):
                logo_img = Image.open(static_path).convert("RGBA")
            elif os.path.exists(qr_logo_val):
                logo_img = Image.open(qr_logo_val).convert("RGBA")
            else:
                logo_img = None

        if logo_img:
            qr_width, qr_height = qr_img.size
            logo_width = int(qr_width * 0.75)
            logo_height = int(logo_width * 0.80)

            logo_img = logo_img.resize((logo_width, logo_height), Image.Resampling.LANCZOS)

            pos_x = (qr_width - logo_width) // 2
            pos_y = (qr_height - logo_height) // 2

            qr_img.paste(logo_img, (pos_x, pos_y), logo_img)

    except Exception as e:
        print(f"Advertencia: No se pudo cargar el logo en el QR: {e}")

    img_io = io.BytesIO()
    qr_img.save(img_io, 'PNG')
    img_io.seek(0)
    return send_file(img_io, mimetype='image/png', download_name=f'QR_{id_vehiculo}.png')

# --- 5. GESTIÓN Y SEGUIMIENTO DE TALLER (ADMINISTRACIÓN) ---
@app.route('/admin/taller')
def admin_taller():
    seguimiento = db.get_seguimiento_admin_taller()
    return render_template(
        'admin_taller.html',
        ots=seguimiento['ots'],
        repuestos=seguimiento['repuestos'],
        total_ots=seguimiento['total_ots'],
        total_repuestos=seguimiento['total_repuestos'],
        repuestos_solicitados=seguimiento['repuestos_solicitados'],
        repuestos_en_tramite=seguimiento['repuestos_en_tramite'],
        repuestos_recibidos=seguimiento['repuestos_recibidos']
    )

@app.route('/admin/repuesto/<int:repuesto_id>/tramitar', methods=['POST'])
def admin_tramitar_repuesto(repuesto_id):
    datos_compra = request.form.get('datos_compra', '').strip()
    observaciones = request.form.get('observaciones', '').strip()

    res = db.confirmar_tramite_repuesto(repuesto_id, datos_compra, observaciones)
    if res.get('success'):
        flash("Repuesto confirmado en trámite de compra con proveedor.")
    else:
        flash(f"Error al confirmar trámite: {res.get('error')}")

    return redirect(url_for('admin_taller'))


# --- 6. AUDITOR DE MANTENIMIENTOS ---
@app.route('/auditor', methods=['GET', 'POST'])
def auditor():
    if request.method == 'POST' and 'nfc_service' in request.form:
        v = find_vehicle_by_key(request.form['nfc_service'])
        if v: return redirect(url_for('auditoria_service', id_vehiculo=v['ID']))
        else: flash("❌ Llave no reconocida para iniciar service.")

    agenda = db.get_all_cronogramas()
    return render_template('auditor.html', agenda=agenda)

@app.route('/auditor/service/<id_vehiculo>', methods=['GET', 'POST'])
def auditoria_service(id_vehiculo):
    v = find_vehicle_by_id(id_vehiculo)
    if not v:
        flash("Unidad no encontrada")
        return redirect(url_for('auditor'))

    if request.method == 'POST':
        detalles = f"REVISIÓN {request.form.get('tipo_revision')}. Obs: {request.form.get('observaciones')}"
        db.record_preventive(
            get_fecha_str(),
            id_vehiculo,
            request.form.get('tipo_revision'),
            'Auditor',
            detalles
        )
        flash("✅ Service registrado correctamente")
        return redirect(url_for('auditor'))

    return render_template('auditoria_service.html', v=v)


# --- 8. RECORTADOR INTELIGENTE DE PDF ---
@app.route('/recortar')
def recortar_pdf():
    fecha_filename = get_arg_time().strftime("%d-%m-%y")
    return render_template('recortar.html', fecha_filename=fecha_filename)

# --- 9. INFORME JERÁRQUICO DE FLOTA (DIAGRAMA DE ÁRBOL) ---
@app.route('/informe/arbol')
def informe_arbol():
    fecha_hoy = get_fecha_str()
    meta = db.get_sync_status()
    ultima_actualizacion = meta.get('ultima_sincronizacion') or get_hora_full_str()

    try:
        unidades_lista, areas_disponibles, tipos_disponibles = db.get_tree_report_data()
    except Exception as e:
        print(f"Error generando informe de árbol desde SQLite: {e}")
        unidades_lista = []
        areas_disponibles = []
        tipos_disponibles = []

    return render_template(
        'informe_arbol.html',
        fecha_hoy=fecha_hoy,
        ultima_actualizacion=ultima_actualizacion,
        rawData_json=json.dumps(unidades_lista, ensure_ascii=False),
        areas_json=json.dumps(areas_disponibles, ensure_ascii=False),
        tipos_json=json.dumps(tipos_disponibles, ensure_ascii=False)
    )

# --- 10. PLANILLA DE GESTIÓN Y EDICIÓN EN LÍNEA ---
@app.route('/admin/planilla')
def admin_planilla():
    datos = get_fleet_data()
    total = len(datos)
    activos = sum(1 for v in datos if 'inactiv' not in v.get('ESTADO','').lower() and 'reparaci' not in v.get('ESTADO','').lower() and 'irrecuperable' not in v.get('ESTADO','').lower())
    inactivos = total - activos
    percent = int((activos / total * 100)) if total else 0
    sync_status = db.get_sync_status()

    return render_template(
        'admin_planilla.html',
        datos=datos,
        total=total,
        activos=activos,
        inactivos=inactivos,
        percent=percent,
        sync_status=sync_status
    )

# --- 11. API DE SINCRONIZACIÓN Y EDICIÓN ---
@app.route('/api/sincronizar_sheets', methods=['GET', 'POST'])
def api_sincronizar_sheets():
    res = db.sincronizar_desde_google_sheets(
        CONF["URL_INFORME_ARBOL"],
        CONF["URL_INFORME_ARBOL_CONTRATADOS"]
    )
    if res.get('success'):
        res['datos'] = get_fleet_data()
    return jsonify(res)

@app.route('/api/vehiculo/actualizar', methods=['POST'])
def api_actualizar_vehiculo():
    data = request.get_json(silent=True) or {}
    vid = data.get('id')
    campo = data.get('campo')
    valor = data.get('valor')
    if not vid or not campo:
        return jsonify({'success': False, 'error': 'Faltan parámetros requeridos (id, campo)'}), 400

    res = db.update_vehicle_cell(vid, campo, valor)
    return jsonify(res)

@app.route('/admin/exportar/excel')
def admin_exportar_excel():
    excel_stream = db.export_fleet_to_excel()
    fecha_nombre = get_arg_time().strftime("%Y%m%d_%H%M")
    return send_file(
        excel_stream,
        as_attachment=True,
        download_name=f"Flota_Municipal_{fecha_nombre}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')