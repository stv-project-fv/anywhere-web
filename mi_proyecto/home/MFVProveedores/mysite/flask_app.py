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
from flask import Flask, render_template, request, send_file, session, redirect, url_for, flash
from flask_caching import Cache

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
# 🧠  LÓGICA DE DATOS
# ==============================================================================

@cache.memoize(timeout=60)
def get_fleet_data():
    try:
        r = requests.get(CONF['URL_FLOTA_PRINCIPAL'])
        r.encoding = 'utf-8'
        return list(csv.DictReader(io.StringIO(r.text)))
    except: return []

def find_vehicle_by_key(key):
    data = get_fleet_data()
    key_clean = key.strip().upper()
    return next((v for v in data if v.get('NFC_KEY', '').strip().upper() == key_clean), None)

def find_vehicle_by_id(id_vehiculo):
    data = get_fleet_data()
    return next((v for v in data if v['ID'] == id_vehiculo), None)

def calcular_dias_actividad(fecha_alta_str):
    try:
        if not fecha_alta_str: return "Sin dato"
        alta = datetime.strptime(fecha_alta_str, "%d/%m/%Y")
        dias = (get_arg_time() - alta).days
        return f"{dias} días"
    except: return "Fecha inválida"

def guardar_registro_simulado(archivo, datos):
    existe = os.path.exists(archivo)
    with open(archivo, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not existe: writer.writerow(datos.keys())
        writer.writerow(datos.values())

# --- LÓGICA DE ESTADOS Y MANTENIMIENTO ---
def get_status_repuesto(id_vehiculo):
    """Lee estado de repuesto O razón de inactividad"""
    archivo = 'estado_repuestos.csv'
    if not os.path.exists(archivo): return None
    try:
        with open(archivo, mode='r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                if row['ID'] == id_vehiculo: return row
    except: pass
    return None

def update_status_repuesto(id_vehiculo, nuevo_estado, nota="", tipo_registro="REPUESTO"):
    """
    tipo_registro: 'REPUESTO' (solicitud) o 'INACTIVIDAD' (razón de baja)
    """
    archivo = 'estado_repuestos.csv'
    fieldnames = ['ID', 'ESTADO', 'NOTA', 'FECHA_UPDATE', 'TIPO_REGISTRO']
    rows = []
    if os.path.exists(archivo):
        with open(archivo, mode='r', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))

    rows = [r for r in rows if r['ID'] != id_vehiculo]

    if nuevo_estado:
        rows.append({
            'ID': id_vehiculo,
            'ESTADO': nuevo_estado,
            'NOTA': nota,
            'FECHA_UPDATE': get_hora_full_str(),
            'TIPO_REGISTRO': tipo_registro
        })

    with open(archivo, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def get_cronograma(id_vehiculo):
    """Obtiene el próximo mantenimiento programado"""
    archivo = 'cronograma_preventivo.csv'
    if not os.path.exists(archivo): return None
    try:
        with open(archivo, mode='r', encoding='utf-8') as f:
            recs = [r for r in csv.DictReader(f) if r['ID'] == id_vehiculo]
            if recs: return recs[-1]
    except: pass
    return None

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
    activos = sum(1 for v in datos if 'inactiv' not in v.get('ESTADO','').lower() and 'reparaci' not in v.get('ESTADO','').lower())
    inactivos = total - activos
    percent = int((activos / total * 100)) if total else 0

    return render_template('index.html', datos=datos, total=total, activos=activos, inactivos=inactivos, percent=percent)

# --- 2. PUESTOS DE CONTROL (SISTEMA DE LLAVE NFC) ---
@app.route('/puesto/<tipo>', methods=['GET', 'POST'])
def puesto_control(tipo):
    titulos = {
        'actividad': 'CONTROL ACCESOS',
        'combustible': 'SURTIDOR',
        'fluidos': 'TALLER FLUIDOS',
        'mantenimiento': 'TALLER MECÁNICO'
    }
    if request.method == 'POST':
        llave = request.form.get('llave_nfc')
        vehiculo = find_vehicle_by_key(llave)
        if vehiculo:
            return redirect(url_for(f'operacion_{tipo}', id_vehiculo=vehiculo['ID']))
        else:
            flash("❌ Llave NFC no reconocida")

    return render_template('puesto_control.html', tipo=tipo, titulo=titulos.get(tipo, 'PUESTO'))

# --- 3. OPERACIONES ---

@app.route('/operacion/actividad/<id_vehiculo>', methods=['GET', 'POST'])
def operacion_actividad(id_vehiculo):
    v = find_vehicle_by_id(id_vehiculo)
    if not v:
        flash("Unidad no encontrada")
        return redirect(url_for('puesto_control', tipo='actividad'))

    if request.method == 'POST':
        accion = request.form['accion']
        motivo = request.form.get('motivo', '')

        if accion == 'REPUESTO_MENOR':
            update_status_repuesto(id_vehiculo, 'PENDIENTE', nota=f"Acceso: {motivo}")
            guardar_registro_simulado('historial_actividad.csv', {
                'FECHA': get_hora_full_str(),
                'ID': id_vehiculo,
                'ACCION': 'NOVEDAD',
                'MOTIVO': f"Solicitud Repuesto: {motivo}",
                'RESPONSABLE': 'Supervisor Puerta'
            })
            flash("✅ Solicitud registrada. Unidad sigue ACTIVA.")
        else:
            guardar_registro_simulado('historial_actividad.csv', {
                'FECHA': get_hora_full_str(),
                'ID': id_vehiculo,
                'ACCION': accion,
                'MOTIVO': motivo,
                'RESPONSABLE': 'Supervisor Puerta'
            })
        return redirect(url_for('puesto_control', tipo='actividad'))

    return render_template('operacion_actividad.html', v=v)

@app.route('/operacion/combustible/<id_vehiculo>', methods=['GET', 'POST'])
def operacion_combustible(id_vehiculo):
    v = find_vehicle_by_id(id_vehiculo)
    if not v:
        flash("Unidad no encontrada")
        return redirect(url_for('puesto_control', tipo='combustible'))

    if request.method == 'POST':
        datos = {
            'FECHA': get_hora_full_str(),
            'ID': id_vehiculo,
            'TIPO': request.form['tipo'],
            'LITROS': request.form['litros'],
            'KM': request.form['km']
        }
        guardar_registro_simulado('historial_combustible.csv', datos)
        return redirect(url_for('puesto_control', tipo='combustible'))

    return render_template('operacion_combustible.html', v=v)

@app.route('/operacion/fluidos/<id_vehiculo>', methods=['GET', 'POST'])
def operacion_fluidos(id_vehiculo):
    v = find_vehicle_by_id(id_vehiculo)
    if not v:
        flash("Unidad no encontrada")
        return redirect(url_for('puesto_control', tipo='fluidos'))

    if request.method == 'POST':
        guardar_registro_simulado('historial_fluidos.csv', {
            'FECHA': get_fecha_str(),
            'ID': id_vehiculo,
            'CAT': request.form['cat'],
            'SUBTIPO': request.form['subtipo'],
            'CANT': request.form['cant']
        })
        return redirect(url_for('puesto_control', tipo='fluidos'))

    return render_template('operacion_fluidos.html', v=v)

@app.route('/operacion/mantenimiento/<id_vehiculo>', methods=['GET', 'POST'])
def operacion_mantenimiento(id_vehiculo):
    v = find_vehicle_by_id(id_vehiculo)
    if not v:
        flash("Unidad no encontrada")
        return redirect(url_for('puesto_control', tipo='mantenimiento'))

    estado_repuesto = get_status_repuesto(id_vehiculo)
    rep_disponible = bool(estado_repuesto and estado_repuesto['ESTADO'] == 'DISPONIBLE')

    if request.method == 'POST':
        tipo = request.form['tipo']
        detalle = request.form.get('detalle', '')
        if tipo == 'EXTERNA':
            update_status_repuesto(id_vehiculo, 'PENDIENTE', nota="Solicitado por mecánico")
        elif tipo == 'RECEPCION_REPUESTO':
            update_status_repuesto(id_vehiculo, None)
            guardar_registro_simulado('historial_mantenimiento.csv', {
                'FECHA': get_fecha_str(),
                'ID': id_vehiculo,
                'TIPO': 'LOGISTICA',
                'DETALLE': 'Repuesto recibido y verificado por taller.'
            })
            flash("✅ Repuesto recibido correctamente.")
            return redirect(url_for('puesto_control', tipo='mantenimiento'))
        if tipo != 'RECEPCION_REPUESTO':
            guardar_registro_simulado('historial_mantenimiento.csv', {
                'FECHA': get_fecha_str(),
                'ID': id_vehiculo,
                'TIPO': tipo,
                'DETALLE': detalle
            })
        return redirect(url_for('puesto_control', tipo='mantenimiento'))

    return render_template('operacion_mantenimiento.html', v=v, rep_disponible=rep_disponible)

# --- 3b. VISUALIZACIÓN DE HISTORIALES ---
@app.route('/historial/<tipo>/<id_vehiculo>')
def ver_historial(tipo, id_vehiculo):
    config_historial = {
        'ingresos':     {'archivo': 'historial_actividad.csv',    'titulo': 'CONTROL DE INGRESOS',       'icon': '📍'},
        'actividad':    {'archivo': 'historial_actividad.csv',    'titulo': 'CONTROL DE INGRESOS',       'icon': '📍'},
        'cronograma':   {'archivo': 'cronograma_preventivo.csv',  'titulo': 'CRONOGRAMA PREVENTIVO',     'icon': '📅'},
        'preventivos':  {'archivo': 'historial_preventivos.csv',  'titulo': 'CRONOGRAMA PREVENTIVO',     'icon': '📅'},
        'mantenimiento':{'archivo': 'historial_mantenimiento.csv','titulo': 'HISTORIAL DE REPARACIONES','icon': '🔧'},
        'reparaciones': {'archivo': 'historial_mantenimiento.csv','titulo': 'HISTORIAL DE REPARACIONES','icon': '🔧'},
        'imagenes':     {'archivo': 'historial_imagenes.csv',     'titulo': 'IMÁGENES',                  'icon': '🖼️'},
        'datos':        {'archivo': 'historial_imagenes.csv',     'titulo': 'IMÁGENES',                  'icon': '🖼️'},
        'combustible':  {'archivo': 'historial_combustible.csv',  'titulo': 'HISTORIAL DE COMBUSTIBLE',  'icon': '⛽'},
        'fluidos':      {'archivo': 'historial_fluidos.csv',      'titulo': 'HISTORIAL DE FLUIDOS',      'icon': '🛢️'}
    }

    cfg = config_historial.get(tipo.lower())
    if not cfg: return "Tipo de historial no válido"

    archivo_local = cfg['archivo']
    registros = []

    if os.path.exists(archivo_local):
        try:
            with open(archivo_local, mode='r', encoding='utf-8') as f:
                all_data = list(csv.DictReader(f))
                registros = [row for row in all_data if row.get('ID') == id_vehiculo]
                registros.sort(key=lambda x: x.get('FECHA', ''), reverse=True)
        except Exception as e:
            print(f"Error leyendo archivo local: {e}")
            registros = []

    columnas = [k for k in registros[0].keys() if k != 'ID'] if registros else []

    return render_template('historial.html', tipo=tipo, id_vehiculo=id_vehiculo, titulo=cfg['titulo'], icon=cfg['icon'], registros=registros, columnas=columnas)

# --- 4. FICHA TÉCNICA ---
@app.route('/ficha/<id_vehiculo>', methods=['GET', 'POST'])
def ficha(id_vehiculo):
    datos = get_fleet_data()
    vehiculo = next((item for item in datos if item["ID"] == id_vehiculo), None)
    if not vehiculo: return "<h1>Unidad no encontrada</h1>"

    if request.method == 'POST':
        if request.form.get('password') == CONF['PASSWORD_ADMIN']:
            session['admin_logged_in'] = True

    es_admin = session.get('admin_logged_in', False)
    specs = {k: v for k, v in vehiculo.items() if k not in CONF['CAMPOS_PUBLICOS_BASE'] and k not in CONF['CAMPOS_PRIVADOS'] and v.strip()}
    priv = {k: v for k, v in vehiculo.items() if k in CONF['CAMPOS_PRIVADOS'] and v.strip()}

    is_inactive = 'inactiv' in vehiculo.get('ESTADO','').lower() or 'reparaci' in vehiculo.get('ESTADO','').lower()
    est_cls = "st-bad" if is_inactive else "st-ok"
    dias = calcular_dias_actividad(vehiculo.get('FECHA_ALTA', ''))

    razon_inactividad = ""
    if is_inactive:
        status_data = get_status_repuesto(id_vehiculo)
        if status_data and status_data.get('TIPO_REGISTRO') == 'INACTIVIDAD':
            razon_inactividad = status_data.get('NOTA', 'Sin motivo especificado')

    return render_template('ficha.html', v=vehiculo, specs=specs, priv=priv, admin=es_admin, est_cls=est_cls, dias=dias, razon_inactiva=razon_inactividad)

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

# --- 5. GESTIÓN DE TALLER (ADMINISTRACIÓN) ---
@app.route('/admin/taller', methods=['GET', 'POST'])
def admin_taller():
    if not session.get('admin_logged_in'):
        if request.method == 'POST' and request.form.get('password') == CONF['PASSWORD_ADMIN']:
            session['admin_logged_in'] = True
        else:
            return render_template('admin_taller_login.html')

    if request.method == 'POST' and 'accion_admin' in request.form:
        vid = request.form['id_vehiculo']
        accion = request.form['accion_admin']
        nota = request.form.get('nota_admin', '')
        if accion == 'MARCAR_PEDIDO': update_status_repuesto(vid, 'PEDIDO', nota)
        elif accion == 'MARCAR_DISPONIBLE': update_status_repuesto(vid, 'DISPONIBLE', nota)
        elif accion == 'BORRAR': update_status_repuesto(vid, None)
        return redirect(url_for('admin_taller'))

    flota = get_fleet_data()
    lista_final = []

    for u in flota:
        estado_rep = get_status_repuesto(u['ID'])
        u['STATUS_DATA'] = estado_rep
        is_broken = 'inactiv' in u.get('ESTADO','').lower() or 'reparaci' in u.get('ESTADO','').lower()
        has_request = estado_rep is not None
        if is_broken or has_request:
            lista_final.append(u)

    c_activas = sum(1 for u in lista_final if 'inactiv' not in u.get('ESTADO','').lower() and 'reparaci' not in u.get('ESTADO','').lower())
    c_inactivas = len(lista_final) - c_activas

    return render_template('admin_taller.html', lista_final=lista_final, c_activas=c_activas, c_inactivas=c_inactivas)

# --- 6. AUDITOR DE MANTENIMIENTOS ---
@app.route('/auditor', methods=['GET', 'POST'])
def auditor():
    if request.method == 'POST' and 'nfc_service' in request.form:
        v = find_vehicle_by_key(request.form['nfc_service'])
        if v: return redirect(url_for('auditoria_service', id_vehiculo=v['ID']))
        else: flash("❌ Llave no reconocida para iniciar service.")

    flota = get_fleet_data()
    cronograma = []
    if os.path.exists('cronograma_preventivo.csv'):
        with open('cronograma_preventivo.csv', mode='r', encoding='utf-8') as f:
            cronograma = list(csv.DictReader(f))

    agenda = []
    for c in cronograma:
        veh = next((u for u in flota if u['ID'] == c['ID']), None)
        if veh:
            c['MARCA'] = veh['MARCA']
            c['MODELO'] = veh['MODELO']
            agenda.append(c)

    return render_template('auditor.html', agenda=agenda)

@app.route('/auditor/service/<id_vehiculo>', methods=['GET', 'POST'])
def auditoria_service(id_vehiculo):
    v = find_vehicle_by_id(id_vehiculo)
    if not v:
        flash("Unidad no encontrada")
        return redirect(url_for('auditor'))

    if request.method == 'POST':
        detalles = f"REVISIÓN {request.form.get('tipo_revision')}. Obs: {request.form.get('observaciones')}"
        guardar_registro_simulado('historial_preventivos.csv', {
            'FECHA': get_fecha_str(),
            'ID': id_vehiculo,
            'TIPO': request.form.get('tipo_revision'),
            'RESPONSABLE': 'Auditor',
            'DETALLE': detalles
        })
        flash("✅ Service registrado correctamente")
        return redirect(url_for('auditor'))

    return render_template('auditoria_service.html', v=v)

# --- 7. TALLER MECÁNICO CENTRALIZADO ---
@app.route('/taller/mecanico', methods=['GET', 'POST'])
def taller_mecanico():
    flota = get_fleet_data()

    if request.method == 'POST' and 'nfc_taller' in request.form:
        v = find_vehicle_by_key(request.form['nfc_taller'])
        if v: return redirect(url_for('taller_unidad', id_vehiculo=v['ID']))
        else: flash("❌ Llave no reconocida.")

    return render_template('taller_mecanico.html', flota=flota)

@app.route('/taller/unidad/<id_vehiculo>', methods=['GET', 'POST'])
def taller_unidad(id_vehiculo):
    return render_template('taller_unidad.html', id_vehiculo=id_vehiculo)

# --- 8. RECORTADOR INTELIGENTE DE PDF ---
@app.route('/recortar')
def recortar_pdf():
    fecha_filename = get_arg_time().strftime("%d-%m-%y")
    return render_template('recortar.html', fecha_filename=fecha_filename)

# --- 9. INFORME JERÁRQUICO DE FLOTA (DIAGRAMA DE ÁRBOL) ---
@app.route('/informe/arbol')
def informe_arbol():
    fecha_hoy = get_fecha_str()
    ultima_actualizacion = get_hora_full_str()
    unidades_lista = []
    areas_disponibles = []
    tipos_disponibles = []

    try:
        # 1. Descarga del CSV publicado de Google Sheets (Flota Principal)
        r = requests.get(CONF["URL_INFORME_ARBOL"])
        r.encoding = 'utf-8'
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = df.columns.str.strip()

        col_tipo = next((c for c in df.columns if 'tipo' in c.lower()), 'TIPO')
        col_unidad = next((c for c in df.columns if 'unidad' in c.lower() or 'id' in c.lower()), 'UNIDAD')
        col_area = next((c for c in df.columns if 'area' in c.lower() or 'área' in c.lower()), 'ÁREA')
        col_estado = next((c for c in df.columns if 'estado' in c.lower()), 'ESTADO')
        col_resumen = next((c for c in df.columns if 'resumen' in c.lower()), None)

        # Descartar filas vacías o inválidas
        df = df.dropna(subset=[col_tipo, col_unidad])
        df = df[df[col_tipo].astype(str).str.strip() != '']
        df = df[df[col_unidad].astype(str).str.strip() != '']
        df = df[~df[col_tipo].astype(str).str.lower().isin(['nan', 'none', 'null', ''])]

        # REQUISITO 2: DISCRIMINAR IRRECUPERABLE (No se consideran bajo ningún concepto)
        df = df[~df[col_estado].astype(str).str.lower().str.contains('irrecuperable', na=False)]

        # Normalización de datos
        df['TIPO_NORM'] = df[col_tipo].astype(str).str.strip().str.upper()
        df['UNIDAD_NORM'] = df[col_unidad].astype(str).str.strip().str.upper()
        df['AREA_NORM'] = df[col_area].fillna('SIN ÁREA ASIGNADA').astype(str).str.strip().str.upper()
        df['AREA_NORM'] = df['AREA_NORM'].replace({'': 'SIN ÁREA ASIGNADA', 'NAN': 'SIN ÁREA ASIGNADA'})

        if col_resumen and col_resumen in df.columns:
            df['RESUMEN_NORM'] = df[col_resumen].fillna('Sin resumen especificado').astype(str).str.strip()
            df['RESUMEN_NORM'] = df['RESUMEN_NORM'].replace({'': 'Sin resumen especificado', 'nan': 'Sin resumen especificado', 'NaN': 'Sin resumen especificado'})
        else:
            df['RESUMEN_NORM'] = 'Sin resumen especificado'

        def clasificar_estado(val):
            val_clean = str(val).strip().lower()
            if val_clean.startswith('funcional'):
                return 'INACTIVAS'
            if 'inactiv' in val_clean or 'reparaci' in val_clean:
                return 'INACTIVAS'
            elif 'activ' in val_clean:
                return 'ACTIVAS'
            return 'INACTIVAS'

        df['ESTADO_CATEGORIA'] = df[col_estado].apply(clasificar_estado)

        for _, row in df.iterrows():
            col_est_raw = str(row[col_estado]).strip()
            is_prestamo = 'PRÉSTAMO' in col_est_raw.upper() or 'PRESTAMO' in col_est_raw.upper()
            area_origen = row['AREA_NORM']

            if is_prestamo:
                est_upper = col_est_raw.upper()
                if ' EN ' in est_upper:
                    dest_part = est_upper.split(' EN ', 1)[1].strip()
                    if 'ALLAN' in dest_part:
                        area_destino = 'DELEGACIÓN ING. ALLAN'
                    elif 'BOSQUES' in dest_part:
                        area_destino = 'DELEGACIÓN BOSQUES'
                    elif 'EQUIPOS VIALES' in dest_part:
                        area_destino = 'EQUIPOS VIALES'
                    elif 'HIGIENE URBANA' in dest_part:
                        area_destino = 'HIGIENE URBANA'
                    elif 'ESPACIOS VERDES' in dest_part:
                        area_destino = 'ESPACIOS VERDES'
                    elif 'CEMENTERIO' in dest_part:
                        area_destino = 'CEMENTERIO'
                    elif 'ALUMBRADO' in dest_part:
                        area_destino = 'ALUMBRADO'
                    else:
                        area_destino = dest_part
                else:
                    area_destino = area_origen

                resumen_norm = f"de {area_origen}"
            else:
                area_destino = area_origen
                resumen_norm = row['RESUMEN_NORM']

            unidades_lista.append({
                'UNIDAD': row['UNIDAD_NORM'],
                'TIPO': row['TIPO_NORM'],
                'AREA': area_destino,
                'AREA_ORIGEN': area_origen,
                'ESTADO_CAT': row['ESTADO_CATEGORIA'],
                'RESUMEN': resumen_norm,
                'CONTRATADO': False,
                'PRESTAMO': is_prestamo
            })

        # REQUISITO 3: SUMAR CONTRATADOS (Hoja AUX 3)
        try:
            r_c = requests.get(CONF["URL_INFORME_ARBOL_CONTRATADOS"])
            r_c.encoding = 'utf-8'
            df_c = pd.read_csv(io.StringIO(r_c.text))
            df_c.columns = df_c.columns.str.strip()

            col_tc = next((c for c in df_c.columns if 'tipo' in c.lower()), 'TIPO_C')
            col_ac = next((c for c in df_c.columns if 'area_c' in c.lower() or 'área_c' in c.lower() or ('area' in c.lower() and 'prestamo' not in c.lower())), 'AREA_C')
            col_cc = next((c for c in df_c.columns if 'cantidad_c' in c.lower() or ('cant' in c.lower() and '_c' in c.lower()) or 'cant' in c.lower()), 'CANTIDAD_C')
            col_em = next((c for c in df_c.columns if 'emerg' in c.lower()), 'SOLO_EMERGENCIA')
            col_dp = next((c for c in df_c.columns if 'de_prestamo' in c.lower() or 'prestamo' in c.lower()), 'DE_PRESTAMO')
            col_cp = next((c for c in df_c.columns if 'cantidad_p' in c.lower() or ('cant' in c.lower() and '_p' in c.lower())), 'CANTIDAD_P')

            for _, row_c in df_c.iterrows():
                tipo_c = str(row_c.get(col_tc, '')).strip().upper()
                area_c = str(row_c.get(col_ac, '')).strip().upper()
                cant_c_raw = str(row_c.get(col_cc, '1')).strip()
                try:
                    cant_c = int(float(cant_c_raw))
                except (ValueError, TypeError):
                    cant_c = 1

                solo_emerg = 'SI' in str(row_c.get(col_em, '')).strip().upper()
                resumen_c = "Unidad Contratada (Solo Emergencia)" if solo_emerg else "Unidad Contratada"

                if tipo_c and area_c and tipo_c not in ['NAN', 'NONE', 'NULL', ''] and area_c not in ['NAN', 'NONE', 'NULL', '']:
                    de_prestamo_raw = str(row_c.get(col_dp, '')).strip().upper()
                    cant_p_raw = str(row_c.get(col_cp, '0')).strip()

                    cant_p = 0
                    area_p = None
                    if de_prestamo_raw and de_prestamo_raw not in ['NAN', 'NONE', 'NULL', '']:
                        try:
                            cant_p = int(float(cant_p_raw))
                        except (ValueError, TypeError):
                            cant_p = 0
                        if cant_p > 0:
                            area_p = de_prestamo_raw

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
        except Exception as e_c:
            print(f"Error cargando hoja de contratados (AUX 3): {e_c}")

        tipos_disponibles = sorted(list(set(u['TIPO'] for u in unidades_lista if u['TIPO'])))
        areas_disponibles = sorted(list(set(u['AREA'] for u in unidades_lista if u['AREA'] and u['AREA'] != 'SIN ÁREA ASIGNADA')))
        if any(u['AREA'] == 'SIN ÁREA ASIGNADA' for u in unidades_lista):
            areas_disponibles.append('SIN ÁREA ASIGNADA')

    except Exception as e:
        print(f"Error al procesar el CSV del árbol: {e}")
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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')