import os
from dotenv import load_dotenv

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

from PIL import Image
import qrcode
import io
import csv
import requests
from flask import Flask, render_template_string, request, send_file, session, redirect, url_for, flash
from datetime import datetime, timedelta
from flask_caching import Cache

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
    archivo = 'estado_repuestos.csv' # Usamos este mismo para guardar el status general
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

    # Si es INACTIVIDAD, borramos registros viejos de inactividad, mantenemos repuestos si queremos
    # Para simplificar, pisamos el estado del vehículo en este archivo local
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
            # Buscamos el último registro cargado para esa unidad
            recs = [r for r in csv.DictReader(f) if r['ID'] == id_vehiculo]
            if recs: return recs[-1] # Retorna el último programado
    except: pass
    return None


# HTML Macro para la cabecera de validación (Reutilizable)
def render_unit_header(v):
    # Se define el tamaño deseado para la imagen más grande
    img_size = "160px"

    return f"""
    <div class="unit-validation-card" style="display: flex; align-items: flex-start; gap: 20px;">
        <img src="{v.get('FOTO_URL','')}" class="unit-photo"
             style="width: {img_size}; height: {img_size}; object-fit: cover; border-radius: 8px; flex-shrink: 0;"
             onerror="this.src='/static/Sin-dato-de-imagen.png'">

        <div class="unit-details" style="flex-grow: 1;">
            <div style="border-left: 5px solid {CONF['COLOR_PRINCIPAL']}; padding-left: 15px; margin-bottom: 20px;">
                <div style="font-size: 28px; font-weight: 900; color: {CONF['COLOR_PRINCIPAL']}; line-height: 1.1;">{v.get('ID','?')}</div>
                <div style="font-size: 14px; font-weight: bold; color: #555; text-transform: uppercase; margin-top: 5px;">{v.get('TIPO','-')}</div>
            </div>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px 20px; font-size: 13px;">

                <div><strong style="color:{CONF['COLOR_PRINCIPAL']}">MARCA:</strong> {v.get('MARCA','-')}</div>
                <div><strong style="color:{CONF['COLOR_PRINCIPAL']}">MODELO:</strong> {v.get('MODELO','-')}</div>
                <div><strong style="color:{CONF['COLOR_PRINCIPAL']}">ÁREA:</strong> {v.get('AREA','-')}</div>
                <div><strong style="color:{CONF['COLOR_PRINCIPAL']}">ESTADO:</strong> {v.get('ESTADO','-')}</div>

                <div><strong style="color:{CONF['COLOR_PRINCIPAL']}">DOMINIO:</strong> {v.get('DOMINIO','-')}</div>
                <div><strong style="color:{CONF['COLOR_PRINCIPAL']}">PATRIMONIO:</strong> {v.get('PATRIMONIO','-')}</div>
                <div><strong style="color:{CONF['COLOR_PRINCIPAL']}">CHOFER:</strong> {v.get('CHOFER','-')}</div>
                <div><strong style="color:{CONF['COLOR_PRINCIPAL']}">LEGAJO:</strong> {v.get('LEGAJO','-')}</div>

            </div>
        </div>
    </div>
    """


# ==============================================================================
# 🎨  ESTILOS CSS
# ==============================================================================
ESTILO_CSS = f"""
<style>
    :root {{ --primary: {CONF['COLOR_PRINCIPAL']}; --secondary: {CONF['COLOR_SECUNDARIO']}; --danger: {CONF['COLOR_ROJO']}; --success: {CONF['COLOR_VERDE']}; }}

    /* FONDO CON IMAGEN */
    body {{
        font-family: 'Segoe UI', Roboto, Helvetica, sans-serif;
        background-color: var(--primary); /* Color de respaldo */
        background-image: url('{CONF.get('BACKGROUND_URL', '')}');
        background-size: cover;
        background-attachment: fixed;
        background-position: center;
        margin: 0; color: #333; min-height: 100vh;
    }}

    /* --- NUEVO ESTILO PARA FICHA TÉCNICA --- */
    .banner-responsive {{
        width: 100%;
        height: auto;       /* Altura automática para no deformar ni recortar */
        display: block;     /* Evita espacios extra debajo de la imagen */
        border-bottom: 5px solid {CONF['COLOR_SECUNDARIO']};
        }}

    /* UTILS */
    .text-center {{ text-align: center; }}
    .hidden {{ display: none; }}
    .mt-20 {{ margin-top: 20px; }}
    .w-100 {{ width: 100%; }}

    /* CONTENEDOR PRINCIPAL */
    .container {{
        max-width: 1200px;
        margin: 40px auto;
        background: rgba(255, 255, 255, 0.96); /* Un poco de transparencia para que luzca el fondo */
        padding: 0;
        border-radius: 12px;
        box-shadow: 0 15px 35px rgba(0,0,0,0.3);
        position: relative;
        overflow: hidden;
    }}
    .content-padding {{ padding: 30px; }}

    /* BANNERS */
    .banner {{ height: 130px; width: 100%; background-size: cover; background-position: center; margin: 0; }}

    /* Estilo específico para PANEL (Borde dorado/secundario) */
    .banner-panel {{ background-image: url('{CONF['BANNER_PANEL_URL']}'); border-bottom: 5px solid var(--secondary); }}

    /* Estilo específico para FICHA (Borde BLANCO) */
    .banner-ficha {{ background-image: url('{CONF['BANNER_FICHA_URL']}'); border-bottom: 5px solid var(--secondary); }}

    /* CABECERA */
    .admin-header {{ display: flex; align-items: center; gap: 20px; border-bottom: 2px solid #eee; padding-bottom: 20px; margin-bottom: 25px; }}

    /* ESTADISTICAS */
    .stats-row {{ display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap; }}
    .stat-box {{ background: #fff; border: 1px solid #e9ecef; border-radius: 8px; padding: 15px; flex: 1; text-align: center; min-width: 120px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
    .stat-val {{ display: block; font-size: 24px; font-weight: bold; color: var(--primary); margin-bottom: 5px; }}

    /* TABLA */
    .list-table {{ width: 100%; border-collapse: separate; border-spacing: 0; font-size: 13px; }}
    .list-table th {{ background: var(--primary); color: white; padding: 12px; text-align: left; }}
    .list-table td {{ padding: 12px; border-bottom: 1px solid #eee; vertical-align: middle; }}
    .action-group {{ display: flex; gap: 5px; align-items: center; }}
    .btn-action {{ background: #333; color: white; text-decoration: none; padding: 6px 12px; border-radius: 4px; font-size: 11px; flex: 1; text-align: center; }}
    .btn-action:hover {{ opacity: 0.8; }}
    .filter-input {{ width: 90%; margin-top: 5px; padding: 6px; border: none; border-radius: 3px; font-size: 11px; }}

    /* FICHA TÉCNICA - GRID ACTUALIZADO */
    .main-grid {{ display: grid; grid-template-columns: 1.6fr 1fr; gap: 30px; align-items: start; }}

    .data-table {{ width: 100%; border-collapse: collapse; font-size: 14px; margin-bottom: 15px; }}
    .data-table td {{ padding: 10px 5px; border-bottom: 1px solid #f0f0f0; }}
    .label {{ font-weight: 600; color: #666; width: 45%; text-transform: uppercase; font-size: 12px; }}
    .value {{ font-weight: 700; color: #000; font-size: 15px; }}

    /* FOTO Y ESTADO (Ajustado para subir posición) */
    .right-column {{ display: flex; flex-direction: column; gap: 0; }} /* Sin gap extra */
    .photo-box {{ background: #eee; border-radius: 8px; overflow: hidden; aspect-ratio: 4/3; margin-bottom: 0; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }}
    .photo-box img {{ width: 100%; height: 100%; object-fit: cover; }}
    .status-badge {{ display: block; padding: 12px; border-bottom-left-radius: 8px; border-bottom-right-radius: 8px; color: white; font-weight: 800; text-align: center; font-size: 18px; letter-spacing: 1px; text-transform: uppercase; }}
    .st-ok {{ background-color: var(--success); }} .st-bad {{ background-color: var(--danger); }}

    .private-box {{ background-color: #fffbf0; border: 1px solid #faeccc; padding: 20px; border-radius: 8px; margin-top: 20px; }}

    /* BOTONES DE HISTORIAL (2x2) */
    .menu-historial-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 15px;
        margin-top: 15px;
    }}
    .btn-historial {{
        padding: 15px 10px;
        border: none;
        border-radius: 8px;
        background: white;
        color: #555;
        font-weight: bold;
        font-size: 13px;
        cursor: pointer;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        border-left: 4px solid var(--secondary);
        transition: all 0.2s ease;
        text-align: left;
        display: flex;
        align-items: center;
        gap: 8px;
    }}
    .btn-historial:hover {{
        transform: translateY(-3px);
        box-shadow: 0 5px 15px rgba(0,0,0,0.15);
        background: var(--primary);
        color: white;
        border-left-color: white;
    }}

    /* ESTILOS LOGIN Y KIOSCO */
    .login-overlay {{ position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0, 155, 119, 0.9); display: flex; align-items: center; justify-content: center; z-index: 999; backdrop-filter: blur(5px); }}
    .login-box {{ background: white; padding: 40px; border-radius: 12px; width: 320px; text-align: center; box-shadow: 0 15px 35px rgba(0,0,0,0.3); }}
    .kiosk-container {{ max-width: 600px; margin: 30px auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); text-align: center; }}
    .unit-validation-card {{ display: flex; gap: 20px; background: #eef2f5; padding: 15px; border-radius: 8px; border-left: 6px solid var(--primary); margin-bottom: 25px; align-items: center; text-align: left; }}
    .unit-photo {{ width: 100px; height: 100px; object-fit: cover; border-radius: 6px; border: 2px solid #ddd; background: #fff; }}
    .unit-details {{ flex: 1; display: grid; grid-template-columns: 1fr 1fr; gap: 5px 15px; font-size: 12px; }}
    .vertical-form {{ display: flex; flex-direction: column; gap: 15px; text-align: left; }}
    .form-input, .form-select {{ padding: 12px; border: 2px solid #ddd; border-radius: 6px; font-size: 16px; width: 100%; box-sizing: border-box; }}
    .big-btn {{ width: 100%; padding: 18px; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer; color: white; transition: 0.2s; }}
    .big-btn:hover {{ opacity: 0.9; transform: translateY(-1px); }}
    .btn-green {{ background: var(--success); }} .btn-red {{ background: var(--danger); }} .btn-blue {{ background: #007bff; }} .btn-orange {{ background: #fd7e14; }} .btn-purple {{ background: #6f42c1; }} .btn-gray {{ background: #6c757d; }}
    .confirm-box {{ background: #fff3cd; border: 2px solid #ffeeba; padding: 20px; border-radius: 8px; margin-top: 20px; text-align: center; }}

    @media (max-width: 600px) {{
        .stats-row {{ flex-direction: column; }}
        .list-table, .list-table th, .list-table td {{ display: block; width: 100%; box-sizing: border-box; }}
        .list-table thead {{ display: none; }}
        .list-table tr {{ margin-bottom: 15px; border: 1px solid #ddd; padding: 10px; background: white; border-radius: 8px; }}
        .list-table td {{ padding: 8px 0; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #eee; }}
        .main-grid {{ display: flex; flex-direction: column-reverse; }}
        .menu-historial-grid {{ grid-template-columns: 1fr; }} /* Botones uno debajo de otro en movil */
    }}
    /* --- NUEVOS ESTILOS AGREGADOS --- */
    /* Tarjeta Taller (Estilo EJEMPLO UNIDAD) */
    /* Ajuste de altura de la tarjeta (de 100px a 80px) */
    .taller-card {{
        display: flex; align-items: stretch; background: white; border: 2px solid #000;
        border-radius: 12px; overflow: hidden; margin-bottom: 12px; height: 75px;
        box-shadow: 0 3px 0 rgba(0,0,0,0.1);
    }}

    .taller-bar {{ width: 25px; flex-shrink: 0; }}

    /* Ajuste de tamaño de letra del ID (de 42px a 32px) */
    .taller-id {{
        font-family: 'Arial Black', sans-serif; font-size: 28px; font-weight: 900;
        color: #000; padding: 0 20px; display: flex; align-items: center;
        justify-content: center; letter-spacing: -1px; min-width: 90px;
    }}
    .taller-info {{
        flex: 1; display: flex; flex-direction: column; justify-content: center;
        padding-left: 15px; border-left: 2px solid #eee; gap: 2px;
    }}
    .taller-type {{ font-weight: 900; font-size: 14px; text-transform: uppercase; color: #000; }}
    .taller-model {{ font-weight: 800; font-size: 12px; text-transform: uppercase; color: #555; }}
    .taller-status {{ font-weight: 900; font-size: 15px; text-transform: uppercase; margin-top: 4px; }}
    .taller-actions {{ display: flex; align-items: center; padding: 0 20px; }}
    .btn-historial-admin {{
        border: 2px solid #000; background: white; color: #000; font-weight: 900;
        text-transform: uppercase; padding: 10px 15px; text-decoration: none;
        font-size: 13px; transition: 0.2s; display: flex; align-items: center; gap: 5px;
    }}
    .btn-historial-admin:hover {{ background: #000; color: white; }}

    /* Layout Admin */
    .admin-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 25px; }}
    .search-bar {{ width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 6px; font-size: 13px; box-sizing: border-box; }}

    @media (max-width: 600px) {{
        .taller-card {{ height: auto; flex-direction: column; text-align: center; }}
        .taller-bar {{ width: 100%; height: 10px; }}
        .taller-id {{ padding: 10px; border-bottom: 1px solid #eee; }}
        .taller-info {{ border-left: none; padding: 15px; }}
        .taller-actions {{ padding-bottom: 20px; justify-content: center; }}
        .admin-grid {{ grid-template-columns: 1fr; }}
    }}
    /* CRONOGRAMA Y AUDITOR */
    .crono-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 15px; }}
    .crono-card {{ background: white; border: 1px solid #ddd; border-radius: 8px; padding: 15px; position: relative; }}
    .crono-date {{ font-size: 24px; font-weight: bold; color: var(--primary); }}
    .crono-type {{ text-transform: uppercase; font-size: 12px; font-weight: bold; color: #666; }}
    .checklist-group {{ background: #f9f9f9; padding: 15px; border-radius: 8px; margin-bottom: 15px; border-left: 4px solid var(--secondary); }}
    .check-item {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; font-size: 14px; border-bottom: 1px dashed #eee; padding-bottom: 5px; }}
    .check-item input[type="checkbox"] {{ width: 20px; height: 20px; }}
</style>
"""

# ==============================================================================
# 🚦  RUTAS DEL SISTEMA
# ==============================================================================
# ==============================================================================
# 🗺️  HERRAMIENTA: MAPA DEL SITIO (ÍNDICE DE RUTAS)
# ==============================================================================

@app.route('/icon-muni.ico')
@app.route('/favicon.ico')
def favicon_muni():
    return send_file(os.path.join(os.path.dirname(__file__), 'icon-muni.ico'), mimetype='image/x-icon')

@app.route('/mapa_sitio')
def mapa_sitio():
    lista_rutas = []

    # Iteramos sobre todas las reglas (rutas) registradas en Flask
    for rule in app.url_map.iter_rules():
        # Ignoramos rutas de archivos estáticos o internas
        if "static" in rule.rule or "GET" not in rule.methods:
            continue

        # Identificamos si la ruta pide parámetros (tiene símbolos < >)
        es_dinamica = "<" in rule.rule

        # Limpiamos los métodos (quitamos HEAD y OPTIONS que ensucian la vista)
        metodos = ", ".join([m for m in rule.methods if m not in ['HEAD', 'OPTIONS']])

        lista_rutas.append({
            "endpoint": rule.endpoint,
            "url": rule.rule,
            "methods": metodos,
            "dynamic": es_dinamica
        })

    # Ordenamos alfabéticamente por URL
    lista_rutas.sort(key=lambda x: x['url'])

    return render_template_string(f"""
    <!DOCTYPE html><html><head>
        <title>Mapa del Sitio</title>
        <meta name="viewport" content="width=device-width,initial-scale=1">
        {{ ESTILO_CSS | safe }}
    </head><body>
        <div class="container">
            <div class="banner banner-panel"></div>
            <div class="content-padding">
                <div class="admin-header">
                    <div style="font-size:40px;">🗺️</div>
                    <div class="titles">
                        <h1 style="margin:0; font-size:28px; color:var(--primary);">MAPA DE RUTAS</h1>
                        <h2 style="margin:5px 0 0 0; font-size:14px; color:#666;">ÍNDICE TÉCNICO DEL SISTEMA</h2>
                    </div>
                    <div style="margin-left:auto;">
                        <a href="/" class="btn-action" style="padding:10px 20px; background:#666; text-decoration:none; color:white; border-radius:4px;">⬅ Volver al Panel</a>
                    </div>
                </div>

                <div style="overflow-x:auto;">
                    <table class="list-table">
                        <thead>
                            <tr>
                                <th>RUTA (URL)</th>
                                <th>NOMBRE DE LA FUNCIÓN</th>
                                <th>MÉTODOS</th>
                                <th style="text-align:center;">ACCIÓN</th>
                            </tr>
                        </thead>
                        <tbody>
                            {{% for ruta in rutas %}}
                            <tr>
                                <td style="font-weight:bold; font-family:monospace; font-size:14px; color:var(--primary);">
                                    {{{{ ruta.url }}}}
                                </td>
                                <td>{{{{ ruta.endpoint }}}}</td>
                                <td><span style="font-size:10px; background:#eee; padding:2px 5px; border-radius:4px;">{{{{ ruta.methods }}}}</span></td>
                                <td style="text-align:center;">
                                    {{% if not ruta.dynamic %}}
                                        <a href="{{{{ ruta.url }}}}" class="btn-action" style="background:var(--success);" target="_blank">IR ➜</a>
                                    {{% else %}}
                                        <span style="color:#999; font-size:11px;">Requiere ID</span>
                                    {{% endif %}}
                                </td>
                            </tr>
                            {{% endfor %}}
                        </tbody>
                    </table>
                </div>

                <div style="margin-top:20px; background:#fff3cd; padding:15px; border-radius:8px; border:1px solid #ffeeba; font-size:13px; color:#856404;">
                    <strong>ℹ️ Nota:</strong> Las rutas que dicen "Requiere ID" (como <code>/ficha/&lt;id&gt;</code>) no tienen botón de "IR" porque necesitan que especifiques un vehículo concreto para funcionar.
                </div>
            </div>
        </div>
    </body></html>
    """, ESTILO_CSS=ESTILO_CSS, rutas=lista_rutas, CONF=CONF)

# --- 1. PANEL DE FLOTA (CON LOGIN) ---
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST' and 'panel_login' in request.form:
        if request.form.get('password') == CONF['PASSWORD_PANEL']:
            session['panel_logged_in'] = True
        else:
            flash("Contraseña incorrecta")

    if not session.get('panel_logged_in'):
        return render_template_string(f"""
        <!DOCTYPE html><html><head><title>Acceso Flota</title><meta name="viewport" content="width=device-width,initial-scale=1">{ESTILO_CSS}</head><body>
            <div class="login-overlay">
                <div class="login-box">
                    <img src="{CONF['LOGO_URL']}" style="width:80px; margin-bottom:20px;">
                    <h2 style="color:var(--primary); margin:0 0 20px 0;">PANEL DE FLOTA</h2>
                    <form method="POST">
                        <input type="hidden" name="panel_login" value="1">
                        <input type="password" name="password" placeholder="Contraseña de Acceso" class="form-input" style="margin-bottom:15px; text-align:center;">
                        <button type="submit" class="big-btn btn-green">INGRESAR</button>
                    </form>
                    {{% with msgs = get_flashed_messages() %}}
                        {{% if msgs %}}<p style="color:white; margin-top:10px; background:#dc3545; padding:5px; border-radius:4px;">{{{{ msgs[0] }}}}</p>{{% endif %}}
                    {{% endwith %}}
                </div>
            </div>
        </body></html>
        """)

    datos = get_fleet_data()
    total = len(datos)
    activos = sum(1 for v in datos if 'inactiv' not in v.get('ESTADO','').lower() and 'reparaci' not in v.get('ESTADO','').lower())
    inactivos = total - activos
    percent = int((activos/total*100)) if total else 0

    # CORRECCIÓN IMPORTANTE: Se agregó la indentación (tabulación) correcta al return
    return render_template_string(f"""
    <!DOCTYPE html><html><head><title>Panel Flota</title><meta name="viewport" content="width=device-width, initial-scale=1">{ESTILO_CSS}</head><body>
        <div class="container">
            <div class="banner banner-panel"></div>

            <div class="content-padding" style="padding: 25px;">
                <div class="admin-header">
                    <img src="{CONF['LOGO_URL']}" style="height: 80px; width: auto;">
                    <div style="display: flex; flex-direction: column; justify-content: center; height: 80px;">
                        <h1 style="margin:0; font-size: 32px; color:var(--primary); line-height: 1.2;">PANEL DE FLOTA</h1>
                        <span style="font-size:14px; color:#888; letter-spacing: 1px; font-weight: 500;">MUNICIPALIDAD DE FLORENCIO VARELA</span>
                    </div>
                </div>

                <div class="stats-row">
                    <div class="stat-box"><span class="stat-val">{total}</span> Unidades</div>
                    <div class="stat-box"><span class="stat-val" style="color:var(--success)">{activos}</span> Activos</div>
                    <div class="stat-box"><span class="stat-val" style="color:var(--danger)">{inactivos}</span> Inactivos</div>
                    <div class="stat-box"><span class="stat-val">{percent}%</span> Operatividad</div>
                </div>

                <div style="overflow-x:auto;">
                    <table class="list-table" id="tablaFlota">
                        <thead>
                            <tr>
                                <th>UNIDAD <br><input type="text" class="filter-input" onkeyup="filtrar(0)" placeholder="Buscar..."></th>
                                <th>TIPO <br><input type="text" class="filter-input" onkeyup="filtrar(1)" placeholder="Buscar..."></th>
                                <th>MARCA/MODELO <br><input type="text" class="filter-input" onkeyup="filtrar(2)" placeholder="Buscar..."></th>
                                <th>PATENTE <br><input type="text" class="filter-input" onkeyup="filtrar(3)" placeholder="Buscar..."></th>
                                <th>ÁREA <br><input type="text" class="filter-input" onkeyup="filtrar(4)" placeholder="Buscar..."></th>
                                <th>ESTADO <br><input type="text" class="filter-input" onkeyup="filtrar(5)" placeholder="Buscar..."></th>
                                <th style="text-align:center;">ACCIONES</th>
                            </tr>
                        </thead>
                        <tbody>
                            {{% for v in datos %}}
                            <tr>
                                <td data-label="UNIDAD"><strong>{{{{ v['ID'] }}}}</strong></td>
                                <td data-label="TIPO">{{{{ v['TIPO'] }}}}</td>
                                <td data-label="MARCA">{{{{ v['MARCA'] }}}} {{{{ v['MODELO'] }}}}</td>
                                <td data-label="PATENTE">{{{{ v['DOMINIO'] }}}}</td>
                                <td data-label="ÁREA">{{{{ v['AREA'] }}}}</td>
                                <td data-label="ESTADO">
                                    <span style="font-weight:bold; color: {{{{ '{CONF['COLOR_ROJO']}' if 'reparaci' in v['ESTADO'].lower() or 'inactiv' in v['ESTADO'].lower() else '{CONF['COLOR_VERDE']}' }}}};">
                                        {{{{ v['ESTADO'] }}}}
                                    </span>
                                </td>
                                <td data-label="ACCIONES">
                                    <div class="action-group">
                                        <a href="/ficha/{{{{ v['ID'] }}}}" class="btn-action" target="_blank">📄 Ficha</a>
                                        <a href="/qr/{{{{ v['ID'] }}}}" class="btn-action" target="_blank">📱 QR</a>
                                    </div>
                                </td>
                            </tr>
                            {{% endfor %}}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        <script>
        function filtrar(n) {{
            var input = document.getElementsByClassName("filter-input")[n];
            var filter = input.value.toUpperCase();
            var table = document.getElementById("tablaFlota");
            var tr = table.getElementsByTagName("tr");
            for (i = 1; i < tr.length; i++) {{
                var td = tr[i].getElementsByTagName("td")[n];
                if (td) {{
                    var txt = td.textContent || td.innerText;
                    tr[i].style.display = txt.toUpperCase().indexOf(filter) > -1 ? "" : "none";
                }}
            }}
        }}
        </script>
    </body></html>
    """, datos=datos, CONF=CONF)

    datos = get_fleet_data()
    total = len(datos)
    activos = sum(1 for v in datos if 'inactiv' not in v.get('ESTADO','').lower() and 'reparaci' not in v.get('ESTADO','').lower())
    inactivos = total - activos
    percent = int((activos/total*100)) if total else 0

# --- 2. PUESTOS DE CONTROL (SISTEMA DE LLAVE NFC) ---
@app.route('/puesto/<tipo>', methods=['GET', 'POST'])
def puesto_control(tipo):
    titulos = {'actividad': 'CONTROL ACCESOS', 'combustible': 'SURTIDOR', 'fluidos': 'TALLER FLUIDOS', 'mantenimiento': 'TALLER MECÁNICO'}
    if request.method == 'POST':
        llave = request.form.get('llave_nfc')
        vehiculo = find_vehicle_by_key(llave)
        if vehiculo:
            return redirect(url_for(f'operacion_{tipo}', id_vehiculo=vehiculo['ID']))
        else:
            flash(f"❌ Llave NFC no reconocida")

    return render_template_string(f"""
    <!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">{ESTILO_CSS}</head><body>

        <div class="banner banner-ficha"></div>

        <div class="kiosk-container">
            <div class="kiosk-content">
                <h2 style="color:var(--primary); margin-bottom:5px;">{titulos.get(tipo, 'PUESTO')}</h2>
                <p style="color:#666; margin-bottom:30px; font-weight:bold;">SUPERVISOR ACTIVO</p>

                <div style="border:3px dashed #ccc; padding:40px; border-radius:10px; background:#fafafa;">
                    <span style="font-size:50px; display:block; margin-bottom:20px; animation:pulse 1.5s infinite">📡</span>
                    <h3>ESPERANDO LLAVE DE ACCESO</h3>
                    <p>Acerque el llavero NFC al lector...</p>
                    <form method="POST"><input type="text" name="llave_nfc" style="opacity:0; position:absolute;" id="nfcInput" autocomplete="off" autofocus></form>
                </div>

                {{% with msgs = get_flashed_messages() %}}
                  {{% if msgs %}}<div style="background:#f8d7da; color:#721c24; padding:10px; margin-top:20px; border-radius:5px;">{{{{ msgs[0] }}}}</div>{{% endif %}}
                {{% endwith %}}
            </div>
        </div>
        <script>
            document.addEventListener('click', function() {{ document.getElementById('nfcInput').focus(); }});
            setTimeout(function(){{ document.getElementById('nfcInput').focus(); }}, 1000);
        </script>
    </body></html>
    """, tipo=tipo, CONF=CONF)

# --- 3. OPERACIONES ---

@app.route('/operacion/actividad/<id_vehiculo>', methods=['GET', 'POST'])
def operacion_actividad(id_vehiculo):
    v = find_vehicle_by_id(id_vehiculo)
    if request.method == 'POST':
        accion = request.form['accion']
        motivo = request.form.get('motivo', '')

        if accion == 'REPUESTO_MENOR':
            update_status_repuesto(id_vehiculo, 'PENDIENTE', nota=f"Acceso: {motivo}")
            guardar_registro_simulado('historial_actividad.csv', {
                'FECHA': get_hora_full_str(), # CORREGIDO: Nombre de función arreglado
                'ID': id_vehiculo, 'ACCION': 'NOVEDAD', 'MOTIVO': f"Solicitud Repuesto: {motivo}", 'RESPONSABLE': 'Supervisor Puerta'
            })
            flash("✅ Solicitud registrada. Unidad sigue ACTIVA.")
        else:
            guardar_registro_simulado('historial_actividad.csv', {
                'FECHA': get_hora_full_str(), # CORREGIDO: Nombre de función arreglado
                'ID': id_vehiculo, 'ACCION': accion, 'MOTIVO': motivo, 'RESPONSABLE': 'Supervisor Puerta'
            })
        return redirect(url_for('puesto_control', tipo='actividad'))

    return render_template_string(f"""
    <!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">{ESTILO_CSS}</head><body>
        <div class="kiosk-container">
            <div class="banner banner-ficha"></div> <div class="kiosk-content">
                <h2 style="color:var(--primary); margin-top:0; margin-bottom:20px;">CONTROL DE ACCESO</h2>
                {render_unit_header(v)}

                <div id="menu-principal">
                    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:15px; margin-bottom:15px;">
                        <button onclick="submitSimple('ENTRADA')" class="big-btn btn-green" style="height:100px; flex-direction:column;">
                            <span style="font-size:30px;">📥</span><br>ENTRADA
                        </button>
                        <button onclick="submitSimple('SALIDA')" class="big-btn btn-blue" style="height:100px; flex-direction:column;">
                            <span style="font-size:30px;">📤</span><br>SALIDA
                        </button>
                    </div>
                    <button onclick="showIrregularidad()" class="big-btn btn-orange">⚠️ REPORTAR IRREGULARIDAD</button>
                </div>

                <div id="menu-irregularidad" class="hidden">
                    <h3 style="color:#d39e00; border-bottom:2px solid #eee; padding-bottom:10px;">SELECCIONE TIPO DE REPORTE</h3>
                    <button onclick="prepForm('INACTIVO')" class="big-btn btn-red" style="width:100%; margin-bottom:10px;">🔴 DECLARAR UNIDAD INACTIVA</button>
                    <button onclick="prepForm('REPUESTO_MENOR')" class="big-btn btn-purple" style="width:100%; margin-bottom:10px;">🟣 REPORTAR NECESIDAD REPUESTO MENOR</button>
                    <button onclick="resetView()" class="big-btn btn-gray" style="width:100%; margin-top:10px;">VOLVER</button>
                </div>

                <div id="form-reporte" class="hidden" style="text-align:left; background:#f9f9f9; padding:20px; border-radius:10px; border:1px solid #ddd;">
                    <h3 id="form-titulo" style="margin-top:0;">DETALLE EL PROBLEMA</h3>
                    <form method="POST">
                        <input type="hidden" name="accion" id="inputAccion">
                        <label class="form-label">Motivo / Detalle:</label>
                        <textarea name="motivo" class="form-input" required rows="3" placeholder="Describa el problema..."></textarea>

                        <div id="msg-confirmacion" style="margin: 15px 0; padding:10px; border-radius:5px; font-weight:bold; font-size:14px; text-align:center;"></div>

                        <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
                            <button type="submit" class="big-btn btn-green">CONFIRMAR</button>
                            <button type="button" onclick="resetView()" class="big-btn btn-gray">CANCELAR</button>
                        </div>
                    </form>
                </div>

                <form id="form-simple" method="POST" class="hidden"><input type="hidden" name="accion" id="simpleAccion"></form>
            </div>
        </div>
        <script>
            function submitSimple(accion) {{ document.getElementById('simpleAccion').value = accion; document.getElementById('form-simple').submit(); }}
            function showIrregularidad() {{ document.getElementById('menu-principal').classList.add('hidden'); document.getElementById('menu-irregularidad').classList.remove('hidden'); }}
            function prepForm(tipo) {{
                document.getElementById('menu-irregularidad').classList.add('hidden');
                document.getElementById('form-reporte').classList.remove('hidden');
                document.getElementById('inputAccion').value = tipo;
                const t = document.getElementById('form-titulo');
                const m = document.getElementById('msg-confirmacion');
                if(tipo === 'INACTIVO') {{
                    t.innerText = "DECLARAR UNIDAD INACTIVA"; t.style.color = "var(--danger)";
                    m.innerHTML = "La unidad pasará a estado <span style='color:red; background:white;'>INACTIVO</span>. ¿Confirma?";
                    m.style.background = "#f8d7da"; m.style.color = "#721c24";
                }} else {{
                    t.innerText = "SOLICITUD DE REPUESTO"; t.style.color = "var(--purple)";
                    m.innerHTML = "Se pedirá repuesto pero la unidad seguirá <span style='color:green; background:white;'>ACTIVA</span>. ¿Confirma?";
                    m.style.background = "#d4edda"; m.style.color = "#155724";
                }}
            }}
            function resetView() {{ document.getElementById('menu-principal').classList.remove('hidden'); document.getElementById('menu-irregularidad').classList.add('hidden'); document.getElementById('form-reporte').classList.add('hidden'); }}
        </script>
    </body></html>""", v=v, CONF=CONF)

@app.route('/operacion/combustible/<id_vehiculo>', methods=['GET', 'POST'])
def operacion_combustible(id_vehiculo):
    v = find_vehicle_by_id(id_vehiculo)
    if request.method == 'POST':
        # CORREGIDO: Usamos get_hora_full_str() directamente
        datos = {'FECHA': get_hora_full_str(), 'ID': id_vehiculo, 'TIPO': request.form['tipo'], 'LITROS': request.form['litros'], 'KM': request.form['km']}
        guardar_registro_simulado('historial_combustible.csv', datos)
        return redirect(url_for('puesto_control', tipo='combustible'))

    return render_template_string(f"""
    <!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">{ESTILO_CSS}</head><body>
        <div class="banner banner-ficha"></div> <div class="kiosk-container">
            <div class="kiosk-content">
                <h2 style="color:var(--orange); margin-top:0; margin-bottom:20px;">⛽ CARGA COMBUSTIBLE</h2>
                {render_unit_header(v)}
                <form method="POST" class="vertical-form">
                    <div class="form-group">
                        <label class="form-label">Tipo de Combustible</label>
                        <select name="tipo" class="form-select"><option>DIESEL (GASOIL)</option><option>NAFTA</option><option>GNC</option></select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Carga en Litros</label>
                        <input type="number" min="0" step="0.1" name="litros" class="form-input" required placeholder="0.0">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Marca del Odómetro de Unidad</label>
                        <input type="number" min="0" name="km" class="form-input" required placeholder="Ej: 154000">
                    </div>
                    <button type="submit" class="big-btn btn-orange" style="margin-top:10px;">REGISTRAR CARGA</button>
                </form>
            </div>
        </div>
    </body></html>""", v=v, CONF=CONF)

@app.route('/operacion/fluidos/<id_vehiculo>', methods=['GET', 'POST'])
def operacion_fluidos(id_vehiculo):
    v = find_vehicle_by_id(id_vehiculo)
    if request.method == 'POST':
        # CORREGIDO: Se usa get_fecha_str()
        guardar_registro_simulado('historial_fluidos.csv', {'FECHA': get_fecha_str(), 'ID': id_vehiculo, 'CAT': request.form['cat'], 'SUBTIPO': request.form['subtipo'], 'CANT': request.form['cant']})
        return redirect(url_for('puesto_control', tipo='fluidos'))

    return render_template_string(f"""
    <!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">{ESTILO_CSS}</head><body>
        <div class="banner banner-ficha"></div> <div class="kiosk-container">
            <div class="kiosk-content">
                <h2 style="color:var(--secondary); margin-top:0; margin-bottom:20px;">🛢️ CARGA DE FLUIDOS</h2>
                {render_unit_header(v)}
                <form method="POST" class="vertical-form">
                    <div class="form-group">
                        <label class="form-label">1. Tipo de Fluido</label>
                        <select name="cat" id="selCat" class="form-select" onchange="updateSubtypes()">
                            <option value="">-- Seleccionar --</option>
                            <option value="ACEITE_MOTOR">Aceite de Motor</option>
                            <option value="TRANSMISION">Fluidos de Transmisión y Diferencial</option>
                            <option value="HIDRAULICO">Hidráulico</option>
                            <option value="REFRIGERANTE">Refrigerante / Anticongelante</option>
                            <option value="ADITIVOS_LIQ">Aditivos líquidos</option>
                            <option value="ADITIVOS_SOL">Aditivos sólidos</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">2. Subtipo</label>
                        <select name="subtipo" id="selSub" class="form-select"></select>
                    </div>
                    <div class="form-group">
                        <label class="form-label" id="lblCant">3. Cantidad</label>
                        <input type="number" min="0" step="0.1" name="cant" class="form-input" required>
                    </div>
                    <button type="submit" class="big-btn btn-purple" style="margin-top:10px;">GUARDAR REGISTRO</button>
                </form>
            </div>
        </div>
        <script>
            const data = {{
                'ACEITE_MOTOR': {{ unit: 'Litros', opts: ['15W40', '10W40', '5W30', 'SAE40', '5W40'] }},
                'TRANSMISION': {{ unit: 'Litros', opts: ['80W90', '85W140', '75W90', 'ATF', 'STOU/UTTO'] }},
                'HIDRAULICO': {{ unit: 'Litros', opts: ['ISO68', 'ISO46', 'ISO32'] }},
                'REFRIGERANTE': {{ unit: 'Litros', opts: ['Orgánico', 'Inorgánico', 'Agua Destilada'] }},
                'ADITIVOS_LIQ': {{ unit: 'Litros', opts: ['AdBlue', 'Líquido de Frenos', 'Líquido Limpiaparabrisas'] }},
                'ADITIVOS_SOL': {{ unit: 'Kilos', opts: ['Grasa de Litio'] }}
            }};
            function updateSubtypes() {{
                const cat = document.getElementById('selCat').value;
                const sub = document.getElementById('selSub');
                const lbl = document.getElementById('lblCant');
                sub.innerHTML = '';
                if(data[cat]) {{
                    lbl.innerText = '3. Cantidad (' + data[cat].unit + ')';
                    data[cat].opts.forEach(opt => {{
                        let o = document.createElement('option');
                        o.value = opt; o.text = opt;
                        sub.add(o);
                    }});
                }} else {{
                    lbl.innerText = '3. Cantidad';
                }}
            }}
        </script>
    </body></html>""", v=v, CONF=CONF)

@app.route('/operacion/mantenimiento/<id_vehiculo>', methods=['GET', 'POST'])
def operacion_mantenimiento(id_vehiculo):
    v = find_vehicle_by_id(id_vehiculo)

    # 1. DEFINICIÓN: Usamos 'rep_disponible'
    estado_repuesto = get_status_repuesto(id_vehiculo)
    rep_disponible = (estado_repuesto and estado_repuesto['ESTADO'] == 'DISPONIBLE')

    if request.method == 'POST':
        tipo = request.form['tipo']
        detalle = request.form.get('detalle', '')
        if tipo == 'EXTERNA':
            update_status_repuesto(id_vehiculo, 'PENDIENTE', nota="Solicitado por mecánico")
        elif tipo == 'RECEPCION_REPUESTO':
            update_status_repuesto(id_vehiculo, None)
            guardar_registro_simulado('historial_mantenimiento.csv', {'FECHA': get_fecha_str(), 'ID': id_vehiculo, 'TIPO': 'LOGISTICA', 'DETALLE': 'Repuesto recibido y verificado por taller.'})
            flash("✅ Repuesto recibido correctamente.")
            return redirect(url_for('puesto_control', tipo='mantenimiento'))
        if tipo != 'RECEPCION_REPUESTO':
            guardar_registro_simulado('historial_mantenimiento.csv', {'FECHA': get_fecha_str(), 'ID': id_vehiculo, 'TIPO': tipo, 'DETALLE': detalle})
        return redirect(url_for('puesto_control', tipo='mantenimiento'))

    return render_template_string(f"""
    <!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">{ESTILO_CSS}</head><body>
        <div class="banner banner-ficha"></div> <div class="kiosk-container">
            <div class="kiosk-content">
                <h2 style="color:var(--danger); margin-top:0; margin-bottom:20px;">🔧 TALLER MANTENIMIENTO</h2>
                {render_unit_header(v)}

                {{% if rep_disponible %}}
                <div style="background:#d4edda; border:2px solid #c3e6cb; color:#155724; padding:20px; border-radius:8px; margin-bottom:20px; animation: pulse 2s infinite;">
                    <h3 style="margin:0 0 10px 0;">📦 ¡REPUESTO DISPONIBLE!</h3>
                    <p>Administración indica que el repuesto ya está en pañol.</p>
                    <form method="POST">
                        <input type="hidden" name="tipo" value="RECEPCION_REPUESTO">
                        <button type="submit" class="big-btn btn-success" style="background:#28a745; font-size:18px;">✅ CONFIRMAR RECEPCIÓN</button>
                    </form>
                </div>
                {{% endif %}}

                <form method="POST" class="vertical-form" id="mainForm">
                    <input type="hidden" name="tipo" id="inputTipo">
                    <div class="form-group"><label class="form-label">Descripción del trabajo / Solicitud:</label><textarea name="detalle" class="form-input" rows="4" placeholder="Describa..."></textarea></div>
                    <div id="btn-group" style="display:grid; grid-template-columns:1fr 1fr; gap:10px;"><button type="button" onclick="confirmarMantenimiento('INTERNA', '¿Confirmar reparación exitosa?')" class="big-btn btn-green">✅ REPARACIÓN EXITOSA</button><button type="button" onclick="confirmarMantenimiento('EXTERNA', '¿Confirmar solicitud de repuesto?')" class="big-btn btn-orange">📝 SOLICITAR REPUESTO</button></div>
                    <div id="confirm-box" class="confirm-box hidden"><h3 id="confirm-msg" style="color:#856404; margin-bottom:20px;"></h3><div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;"><button type="submit" class="big-btn btn-green">CONFIRMAR</button><button type="button" onclick="cancelar()" class="big-btn btn-gray">CANCELAR</button></div></div>
                </form>
            </div>
        </div>
        <script>
            function confirmarMantenimiento(tipo, msg) {{ if(document.querySelector('textarea').value.trim() === "") {{ alert("Por favor ingrese una descripción."); return; }} document.getElementById('inputTipo').value = tipo; document.getElementById('btn-group').classList.add('hidden'); document.getElementById('confirm-box').classList.remove('hidden'); document.getElementById('confirm-msg').innerText = msg; }}
            function cancelar() {{ document.getElementById('btn-group').classList.remove('hidden'); document.getElementById('confirm-box').classList.add('hidden'); }}
        </script>
    </body></html>""", v=v, rep_disponible=rep_disponible, CONF=CONF)
    # 2. USO: Aquí al final pasamos 'rep_disponible=rep_disponible'

# --- 3b. VISUALIZACIÓN DE HISTORIALES (NUEVA RUTA CORREGIDA) ---
@app.route('/historial/<tipo>/<id_vehiculo>')
def ver_historial(tipo, id_vehiculo):
    # Mapeo de tipos a ARCHIVOS LOCALES (Los mismos nombres que usas al guardar)
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

    # LEER DEL ARCHIVO LOCAL (En lugar de URL externa)
    if os.path.exists(archivo_local):
        try:
            with open(archivo_local, mode='r', encoding='utf-8') as f:
                all_data = list(csv.DictReader(f))
                # Filtrar solo los registros de este vehículo
                registros = [row for row in all_data if row.get('ID') == id_vehiculo]
                # Intentar ordenar por fecha (asumiendo columna FECHA formato YYYY-MM-DD o similar)
                registros.sort(key=lambda x: x.get('FECHA', ''), reverse=True)
        except Exception as e:
            print(f"Error leyendo archivo local: {e}")
            registros = []

    # Obtener cabeceras dinámicamente si hay registros
    columnas = [k for k in registros[0].keys() if k != 'ID'] if registros else []

    return render_template_string(f"""
    <!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Historial {{{{ tipo }}}}</title>{ESTILO_CSS}</head><body>
        <div class="banner banner-ficha"></div>
        <div class="container">
            <div class="content-padding">
                <div class="admin-header">
                    <div style="font-size:40px;">{{{{ icon }}}}</div>
                    <div>
                        <h1 style="margin:0; font-size:28px; color:var(--primary);">{{{{ titulo }}}}</h1>
                        <h2 style="margin:5px 0 0 0; font-size:16px; color:#666;">UNIDAD: <span style="color:var(--secondary); font-weight:900;">{{{{ id_vehiculo }}}}</span></h2>
                    </div>
                    <div style="margin-left:auto;">
                        <a href="/ficha/{{{{ id_vehiculo }}}}" class="big-btn btn-gray" style="padding:10px 20px; font-size:14px; text-decoration:none;">⬅ Volver a Ficha</a>
                    </div>
                </div>

                <div style="overflow-x:auto; background:white; border-radius:8px; box-shadow:0 2px 10px rgba(0,0,0,0.05);">
                    {{% if registros %}}
                        <table class="list-table">
                            <thead>
                                <tr>
                                    {{% for col in columnas %}}
                                        <th>{{{{ col }}}}</th>
                                    {{% endfor %}}
                                </tr>
                            </thead>
                            <tbody>
                                {{% for row in registros %}}
                                    <tr>
                                        {{% for col in columnas %}}
                                            <td>{{{{ row[col] }}}}</td>
                                        {{% endfor %}}
                                    </tr>
                                {{% endfor %}}
                            </tbody>
                        </table>
                    {{% else %}}
                        <div style="padding:50px 20px; text-align:center; color:#777;">
                            <div style="font-size:48px; margin-bottom:15px; opacity:0.6;">{{{{ icon }}}}</div>
                            <h3 style="font-size:20px; color:#555; margin-bottom:8px;">Aún no hay datos registrados para esta unidad.</h3>
                            <p style="font-size:14px; color:#999; margin:0;">No se encontraron registros de {{{{ titulo.lower() }}}} cargados en el sistema.</p>
                        </div>
                    {{% endif %}}
                </div>
            </div>
        </div>
    </body></html>
    """, tipo=tipo, id_vehiculo=id_vehiculo, titulo=cfg['titulo'], icon=cfg['icon'], registros=registros, columnas=columnas, CONF=CONF)

# --- 4. FICHA TÉCNICA (ACTUALIZADA) ---
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

    # Obtener razón de inactividad si corresponde
    razon_inactividad = ""
    if is_inactive:
        status_data = get_status_repuesto(id_vehiculo)
        # Si hay una nota guardada y el estado coincide con inactividad/pendiente
        if status_data and status_data.get('TIPO_REGISTRO') == 'INACTIVIDAD':
            razon_inactividad = status_data.get('NOTA', 'Sin motivo especificado')

    return render_template_string(f"""
    <!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Ficha {{{{ v['ID'] }}}}</title>{ESTILO_CSS}</head><body>

        <div class="container">

            <img src="{CONF['BANNER_FICHA_URL']}" class="banner-responsive" alt="Banner Municipalidad">

            <div class="content-padding">
                <div class="admin-header">
                    <img src="{CONF['LOGO_URL']}" style="width:80px;">
                    <div class="titles">
                        <h1 style="margin:0; font-size:28px; color:var(--primary);">FICHA TÉCNICA</h1>
                        <h2 style="margin:5px 0 0 0; font-size:14px; color:#666;">MUNICIPALIDAD DE FLORENCIO VARELA</h2>
                    </div>
                </div>

                <div class="main-grid">
                    <div class="left-column">
                        <div style="border-left:5px solid var(--primary); padding-left:15px; margin-bottom:25px;">
                            <div style="font-size:32px; font-weight:900; color:var(--primary); line-height:1;">{{{{ v['ID'] }}}}</div>
                            <div style="font-size:18px; font-weight:bold; color:#555; margin-top:5px;">{{{{ v['TIPO'] }}}}</div>
                        </div>

                        <table class="data-table">
                            <tr><td class="label">MARCA/MODELO</td><td class="value">{{{{ v['MARCA'] }}}} {{{{ v['MODELO'] }}}}</td></tr>
                            <tr><td class="label">DOMINIO</td><td class="value">{{{{ v['DOMINIO'] }}}}</td></tr>
                            <tr><td class="label">AÑO</td><td class="value">{{{{ v['AÑO'] }}}}</td></tr>
                            <tr><td class="label">ÁREA</td><td class="value">{{{{ v['AREA'] }}}}</td></tr>
                        </table>

                        {{% if specs %}}
                        <div style="background:#f4f4f4; padding:8px 10px; font-weight:bold; font-size:12px; margin-top:20px; border-radius:4px; color:#555;">ESPECIFICACIONES TÉCNICAS</div>
                        <table class="data-table">
                            {{% for k, val in specs.items() %}}<tr><td class="label">{{{{ k }}}}</td><td class="value">{{{{ val }}}}</td></tr>{{% endfor %}}
                        </table>
                        {{% endif %}}

                        {{% if admin %}}
                            <div class="private-box">
                                <div style="display:flex; justify-content:space-between; margin-bottom:15px; border-bottom:1px solid #faeccc; padding-bottom:10px;">
                                    <span style="font-weight:bold; color:#d39e00;">🔒 DATOS PRIVADOS</span>
                                    <a href="/logout" style="color:#dc3545; font-size:12px; text-decoration:none;">Cerrar Sesión ✖</a>
                                </div>
                                <table class="data-table">
                                    {{% for k, val in priv.items() %}}<tr><td class="label">{{{{ k }}}}</td><td class="value" style="color:#555">{{{{ val }}}}</td></tr>{{% endfor %}}
                                </table>

                                {{% if razon_inactiva %}}
                                <div style="background:#f8d7da; color:#721c24; padding:10px; border-radius:5px; margin-top:10px; font-weight:bold; border:1px solid #f5c6cb;">
                                    ⚠️ UNIDAD INACTIVA: {{{{ razon_inactiva }}}}
                                </div>
                                {{% endif %}}

                                <div style="margin-top:20px;">
                                    <div style="font-size:12px; font-weight:bold; margin-bottom:10px; color:#666; text-transform:uppercase;">Historiales Operativos:</div>
                                    <div class="menu-historial-grid">
                                        <a href="/historial/ingresos/{{{{ v['ID'] }}}}" class="btn-historial"><span>📍</span> CONTROL INGRESOS</a>
                                        <a href="/historial/cronograma/{{{{ v['ID'] }}}}" class="btn-historial"><span>📅</span> CRONOGRAMA PREVENTIVO</a>
                                        <a href="/historial/mantenimiento/{{{{ v['ID'] }}}}" class="btn-historial"><span>🔧</span> HISTORIAL REPARACIONES</a>
                                        <a href="/historial/imagenes/{{{{ v['ID'] }}}}" class="btn-historial"><span>🖼️</span> IMÁGENES</a>
                                    </div>
                                </div>
                            </div>
                        {{% else %}}
                            <div style="margin-top:30px; border-top:1px dashed #ccc; padding-top:20px;">
                                <button onclick="document.getElementById('login').style.display='block';this.style.display='none'" class="login-btn" style="background:none; border:none; color:#888; text-decoration:underline; cursor:pointer;">🔒 Acceso Administrativo</button>
                                <form id="login" method="POST" style="display:none; margin-top:10px; text-align:left;">
                                    <div style="display:flex; gap:10px;">
                                        <input type="password" name="password" placeholder="Contraseña..." style="padding:8px; border:1px solid #ccc; border-radius:4px; flex:1;">
                                        <button type="submit" style="padding:8px 15px; background:var(--primary); color:white; border:none; border-radius:4px; cursor:pointer;">Entrar</button>
                                    </div>
                                </form>
                            </div>
                        {{% endif %}}
                    </div>

                    <div class="right-column">
                        <div class="photo-box">
                            <img src="{{{{ v['FOTO_URL'] }}}}" onerror="this.src='/static/Sin-dato-de-imagen.png'">
                        </div>
                        <div class="status-badge {{{{ est_cls }}}}">{{{{ v['ESTADO'] }}}}</div>
                    </div>
                </div>
            </div> </div> </body></html>
    """, v=vehiculo, specs=specs, priv=priv, admin=es_admin, est_cls=est_cls, dias=dias, razon_inactiva=razon_inactividad, CONF=CONF)
@app.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    return redirect(request.referrer)

@app.route('/qr/<id_vehiculo>')
def generate_qr(id_vehiculo):
    # 1. Configurar QR con ALTA corrección de errores (H) para permitir tapar el centro
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H, # Vital para poner logos
        box_size=15,
        border=2
    )
    qr.add_data(f"{request.host_url}ficha/{id_vehiculo}")
    qr.make(fit=True)

    # 2. Crear imagen base usando el color principal de la marca (RGB)
    # Convertimos a 'RGBA' para manejar transparencias correctamente
    qr_img = qr.make_image(fill_color=CONF['COLOR_PRINCIPAL'], back_color="white").convert('RGBA')

    # 3. Intentar incrustar el logo
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
            # Calcular tamaño del logo (75% ancho con relación achatada)
            qr_width, qr_height = qr_img.size
            logo_width = int(qr_width * 0.75)
            logo_height = int(logo_width * 0.80)

            # Redimensionar el logo con alta calidad
            logo_img = logo_img.resize((logo_width, logo_height), Image.Resampling.LANCZOS)

            # Centrar logo
            pos_x = (qr_width - logo_width) // 2
            pos_y = (qr_height - logo_height) // 2

            # Pegar el logo sobre el QR
            qr_img.paste(logo_img, (pos_x, pos_y), logo_img)

    except Exception as e:
        print(f"Advertencia: No se pudo cargar el logo en el QR: {e}")
        # Si falla (ej: sin internet), se entrega el QR normal sin logo y no se rompe nada.

    # 4. Enviar imagen final
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
            return render_template_string(f"""<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">{ESTILO_CSS}</head><body><div class="login-overlay"><div class="login-box"><h3>ACCESO ADMINISTRACIÓN TALLER</h3><form method="POST"><input type="password" name="password" placeholder="Contraseña Admin" class="form-input"><br><br><button class="big-btn btn-blue">ENTRAR</button></form></div></div></body></html>""")

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

    # NUEVA LÓGICA: Mostrar si está Inactivo O si tiene repuesto pendiente
    for u in flota:
        estado_rep = get_status_repuesto(u['ID'])
        u['STATUS_DATA'] = estado_rep
        is_broken = 'inactiv' in u.get('ESTADO','').lower() or 'reparaci' in u.get('ESTADO','').lower()
        has_request = estado_rep is not None
        if is_broken or has_request:
            lista_final.append(u)

    # Contadores
    c_activas = sum(1 for u in lista_final if 'inactiv' not in u.get('ESTADO','').lower() and 'reparaci' not in u.get('ESTADO','').lower())
    c_inactivas = len(lista_final) - c_activas

    return render_template_string(f"""
    <!DOCTYPE html><html><head><title>Gestión Taller</title><meta name="viewport" content="width=device-width, initial-scale=1">{ESTILO_CSS}</head><body>
        <div class="banner banner-panel"></div>
        <div class="container" style="max-width:1400px;">
            <div class="content-padding">
                <div class="admin-header">
                    <div>
                        <h1 style="margin:0; color:var(--primary);">GESTIÓN DE TALLER</h1>
                        <a href="/" style="color:#666; text-decoration:none; font-size:14px;">⬅ Volver al Panel Principal</a>
                    </div>
                    <div style="text-align:right;">
                        <div style="font-weight:bold; color:var(--danger); font-size:20px;">{len(lista_final)} UNIDADES EN ATENCIÓN</div>
                        <div style="font-size:12px; color:#555;">
                            <span style="color:var(--success)">● {c_activas} Activas</span> |
                            <span style="color:var(--danger)">● {c_inactivas} Inactivas</span>
                        </div>
                    </div>
                </div>

                <div class="admin-grid">
                    <div>
                        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:2px solid #ccc; padding-bottom:10px; margin-bottom:15px;">
                            <h3 style="margin:0; color:#444;">🚜 PARQUE EN ATENCIÓN</h3>
                            <input type="text" id="filterIzq" onkeyup="filterDivs('izq', 'filterIzq')" placeholder="🔍 Buscar..." class="search-bar" style="width:150px; margin:0;">
                        </div>
                        <div id="container-izq">
                        {{% for u in lista_final %}}
                            {{% set is_bad = 'inactiv' in u['ESTADO'].lower() or 'reparaci' in u['ESTADO'].lower() %}}
                            {{% set color_estado = '#dc3545' if is_bad else '#28a745' %}}

                            <div class="taller-card search-item">
                                <div class="taller-bar" style="background-color: {{{{ color_estado }}}};"></div>
                                <div class="taller-id">{{{{ u['ID'] }}}}</div>
                                <div class="taller-info">
                                    <div class="taller-type">{{{{ u['TIPO'] }}}}</div>
                                    <div class="taller-model">{{{{ u['MARCA'] }}}} {{{{ u['MODELO'] }}}}</div>
                                    <div class="taller-status" style="color: {{{{ color_estado }}}};">{{{{ u['ESTADO'] }}}}</div>
                                </div>
                                <div class="taller-actions">
                                    <a href="/historial/mantenimiento/{{{{ u['ID'] }}}}" target="_blank" class="btn-historial-admin">
                                        HISTORIAL ➜
                                    </a>
                                </div>
                            </div>
                        {{% endfor %}}
                        </div>
                    </div>

                    <div style="background:#fffbf0; padding:15px; border-radius:10px; border:1px solid #ffeeba;">
                        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:2px solid #e0c070; padding-bottom:10px; margin-bottom:15px;">
                            <h3 style="margin:0; color:#856404;">📦 GESTIÓN DE SOLICITUDES</h3>
                            <input type="text" id="filterDer" onkeyup="filterDivs('der', 'filterDer')" placeholder="🔍 Buscar..." class="search-bar" style="width:150px; margin:0;">
                        </div>
                        <div id="container-der">
                        {{% for u in lista_final %}}
                            {{% if u['STATUS_DATA'] %}}
                            <div class="search-item" style="background:white; padding:15px; border-radius:8px; margin-bottom:15px; box-shadow:0 2px 5px rgba(0,0,0,0.05);">
                                <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
                                    <span style="font-weight:bold;">{{{{ u['ID'] }}}}</span>
                                    {{% if u['STATUS_DATA']['ESTADO'] == 'PENDIENTE' %}}<span style="background:var(--danger); color:white; padding:2px 6px; border-radius:4px; font-size:10px;">PENDIENTE</span>
                                    {{% elif u['STATUS_DATA']['ESTADO'] == 'PEDIDO' %}}<span style="background:var(--secondary); color:white; padding:2px 6px; border-radius:4px; font-size:10px;">PEDIDO</span>
                                    {{% elif u['STATUS_DATA']['ESTADO'] == 'DISPONIBLE' %}}<span style="background:var(--success); color:white; padding:2px 6px; border-radius:4px; font-size:10px;">DISPONIBLE</span>{{% endif %}}
                                </div>
                                <div style="font-size:12px; color:#555; background:#f9f9f9; padding:8px; border-radius:4px; margin-bottom:10px;">
                                    {{{{ u['STATUS_DATA']['NOTA'] }}}}
                                    <div style="font-size:10px; color:#999; margin-top:4px; text-align:right;">{{{{ u['STATUS_DATA']['FECHA_UPDATE'] }}}}</div>
                                </div>
                                <form method="POST">
                                    <input type="hidden" name="id_vehiculo" value="{{{{ u['ID'] }}}}">
                                    <input type="text" name="nota_admin" placeholder="Nota interna..." class="search-bar" style="margin-bottom:8px;">
                                    <div style="display:flex; gap:5px;">
                                        <button type="submit" name="accion_admin" value="MARCAR_PEDIDO" class="btn-action" style="background:var(--secondary); border:none; flex:1;">🟡 Pedido</button>
                                        <button type="submit" name="accion_admin" value="MARCAR_DISPONIBLE" class="btn-action" style="background:var(--success); border:none; flex:1;">🟢 Llegó</button>
                                        <button type="submit" name="accion_admin" value="BORRAR" class="btn-action" style="background:#999; border:none; width:30px;">✖</button>
                                    </div>
                                </form>
                            </div>
                            {{% endif %}}
                        {{% endfor %}}
                        </div>
                    </div>
                </div>
            </div>
        </div>
        <script>
        function filterDivs(containerId, inputId) {{
            var filter = document.getElementById(inputId).value.toUpperCase();
            var items = document.getElementById('container-' + containerId).getElementsByClassName('search-item');
            for (var i = 0; i < items.length; i++) {{
                var txt = items[i].textContent || items[i].innerText;
                items[i].style.display = txt.toUpperCase().indexOf(filter) > -1 ? "" : "none";
            }}
        }}
        </script>
    </body></html>
    """, lista_final=lista_final, c_activas=c_activas, c_inactivas=c_inactivas, CONF=CONF)

    # --- AUDITOR DE MANTENIMIENTOS ---
@app.route('/auditor', methods=['GET', 'POST'])
def auditor():
    if request.method == 'POST' and 'nfc_service' in request.form:
        v = find_vehicle_by_key(request.form['nfc_service'])
        if v: return redirect(url_for('auditoria_service', id_vehiculo=v['ID']))
        else: flash("❌ Llave no reconocida para iniciar service.")

    flota = get_fleet_data()
    # Logica simple de calendario: leemos cronograma_preventivo.csv
    cronograma = []
    if os.path.exists('cronograma_preventivo.csv'):
        with open('cronograma_preventivo.csv', mode='r', encoding='utf-8') as f:
            cronograma = list(csv.DictReader(f))

    # Unir datos
    agenda = []
    for c in cronograma:
        veh = next((u for u in flota if u['ID'] == c['ID']), None)
        if veh:
            c['MARCA'] = veh['MARCA']
            c['MODELO'] = veh['MODELO']
            agenda.append(c)

    return render_template_string(f"""
    <!DOCTYPE html><html><head><title>Auditor Mantenimiento</title><meta name="viewport" content="width=device-width,initial-scale=1">{ESTILO_CSS}</head><body>
        <div class="banner banner-panel"></div>
        <div class="container">
            <div class="content-padding">
                <div class="admin-header">
                    <div><h1 style="color:var(--primary);">🕵️ AUDITOR DE MANTENIMIENTO</h1><a href="/" style="color:#666;">⬅ Volver</a></div>
                </div>

                <div style="background:#e3f2fd; padding:20px; border-radius:10px; margin-bottom:30px; text-align:center;">
                    <h3>🚀 INICIAR REVISIÓN / SERVICE</h3>
                    <p>Escanee la llave de la unidad para comenzar la carga del checklist.</p>
                    <form method="POST">
                        <input type="text" name="nfc_service" placeholder="Click aquí y escanee NFC..." class="form-input" style="width:300px; text-align:center;" autofocus autocomplete="off">
                    </form>
                    {{% with msgs = get_flashed_messages() %}}{{% if msgs %}}<p style="color:red">{{{{ msgs[0] }}}}</p>{{% endif %}}{{% endwith %}}
                </div>

                <h3>📅 CRONOGRAMA GENERAL DE PREVENTIVOS</h3>
                <input type="text" id="filtroCrono" onkeyup="filtrarCrono()" placeholder="🔍 Filtrar por unidad, fecha, tipo..." class="search-bar">
                <div class="crono-grid" id="gridCrono">
                    {{% for item in agenda %}}
                    <div class="crono-card">
                        <div class="crono-date">{{{{ item['FECHA_PROGRAMADA'] }}}}</div>
                        <div style="font-weight:900; font-size:18px;">{{{{ item['ID'] }}}}</div>
                        <div style="font-size:12px;">{{{{ item['MARCA'] }}}} {{{{ item['MODELO'] }}}}</div>
                        <hr>
                        <div class="crono-type">{{{{ item['TIPO_MANTENIMIENTO'] }}}}</div>
                        <div style="color:{{{{ 'green' if item['ESTADO']=='REALIZADO' else 'orange' }}}}; font-weight:bold;">
                            {{{{ item['ESTADO'] }}}}
                        </div>
                    </div>
                    {{% endfor %}}
                </div>
            </div>
        </div>
        <script>
        function filtrarCrono() {{
            var filter = document.getElementById("filtroCrono").value.toUpperCase();
            var cards = document.getElementsByClassName("crono-card");
            for (i = 0; i < cards.length; i++) {{
                var txt = cards[i].innerText;
                cards[i].style.display = txt.toUpperCase().indexOf(filter) > -1 ? "" : "none";
            }}
        }}
        </script>
    </body></html>""", agenda=agenda, CONF=CONF)

@app.route('/auditor/service/<id_vehiculo>', methods=['GET', 'POST'])
def auditoria_service(id_vehiculo):
    v = find_vehicle_by_id(id_vehiculo)
    if request.method == 'POST':
        # Guardar el checklist y actualizar cronograma
        detalles = f"REVISIÓN {request.form.get('tipo_revision')}. Obs: {request.form.get('observaciones')}"
        guardar_registro_simulado('historial_preventivos.csv', {
            'FECHA': get_fecha_str(), 'ID': id_vehiculo,
            'TIPO': request.form.get('tipo_revision'), 'RESPONSABLE': 'Auditor',
            'DETALLE': detalles
        })
        flash("✅ Service registrado correctamente")
        return redirect(url_for('auditor'))

    return render_template_string(f"""
    <!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">{ESTILO_CSS}</head><body>
        <div class="container" style="max-width:800px;">
            <div class="content-padding">
                <h2 style="color:var(--primary);">📋 CHECKLIST DE SERVICE</h2>
                {render_unit_header(v)}

                <form method="POST">
                    <div class="form-group">
                        <label class="form-label">Tipo de Revisión</label>
                        <select name="tipo_revision" class="form-select">
                            <option>DIARIA / PRE-VIAJE</option>
                            <option>PREVENTIVO PROGRAMADO (KM/HORAS)</option>
                        </select>
                    </div>

                    <div class="checklist-group">
                        <h4>1. EXTERIOR & CHASIS</h4>
                        <label class="check-item"><input type="checkbox"> Neumáticos (Presión/Desgaste)</label>
                        <label class="check-item"><input type="checkbox"> Luces (Giro, Freno, Altas/Bajas)</label>
                        <label class="check-item"><input type="checkbox"> Carrocería y Suspensión visible</label>
                    </div>

                    <div class="checklist-group">
                        <h4>2. INTERIOR CABINA</h4>
                        <label class="check-item"><input type="checkbox"> Frenos (Prueba de pedal)</label>
                        <label class="check-item"><input type="checkbox"> Tablero (Testigos, Combustible)</label>
                        <label class="check-item"><input type="checkbox"> Dirección (Juego libre)</label>
                    </div>

                    <div class="checklist-group">
                        <h4>3. MOTOR (APAGADO)</h4>
                        <label class="check-item"><input type="checkbox"> Nivel Aceite</label>
                        <label class="check-item"><input type="checkbox"> Refrigerante</label>
                        <label class="check-item"><input type="checkbox"> Correas y Mangueras</label>
                        <label class="check-item"><input type="checkbox"> Fugas visibles</label>
                    </div>

                    <div class="form-group">
                        <label class="form-label">Observaciones Adicionales / Trabajos Realizados</label>
                        <textarea name="observaciones" class="form-input" rows="3" placeholder="Detalle aquí si cambió aceite, filtros, etc..."></textarea>
                    </div>

                    <button type="submit" class="big-btn btn-green">💾 GUARDAR REVISIÓN</button>
                </form>
            </div>
        </div>
    </body></html>""", v=v, CONF=CONF)
    # --- TALLER MECÁNICO CENTRALIZADO ---
@app.route('/taller/mecanico', methods=['GET', 'POST'])
def taller_mecanico():
    # Menú principal de mecánicos
    flota = get_fleet_data()

    # Manejo de Login con LLave para editar
    if request.method == 'POST' and 'nfc_taller' in request.form:
        v = find_vehicle_by_key(request.form['nfc_taller'])
        if v: return redirect(url_for('taller_unidad', id_vehiculo=v['ID']))
        else: flash("❌ Llave no reconocida.")

    return render_template_string(f"""
    <!DOCTYPE html><html><head><title>Taller Mecánico</title><meta name="viewport" content="width=device-width,initial-scale=1">{ESTILO_CSS}</head><body>
        <div class="banner banner-panel"></div>
        <div class="container">
            <div class="content-padding">
                <div class="admin-header">
                    <div><h1 style="color:var(--danger);">🔧 TALLER MECÁNICO CORRALÓN</h1></div>
                </div>

                <div style="background:#fff3cd; padding:20px; border-radius:10px; margin-bottom:20px; text-align:center; border:1px solid #ffeeba;">
                    <h3>ACCEDER A UNIDAD</h3>
                    <p>Escanee la llave o ingrese manualmente para registrar reparación/combustible.</p>
                    <form method="POST">
                        <input type="text" name="nfc_taller" placeholder="Escanee llave NFC..." class="form-input" style="width:300px; text-align:center;" autofocus autocomplete="off">
                    </form>
                    {{% with msgs = get_flashed_messages() %}}{{% if msgs %}}<p style="color:red">{{{{ msgs[0] }}}}</p>{{% endif %}}{{% endwith %}}
                </div>

                <h3>LISTADO DE FLOTA</h3>
                <input type="text" id="filtroTaller" onkeyup="filtrarTaller()" placeholder="🔍 Buscar unidad..." class="search-bar">

                <div style="margin-top:15px;" id="listaTaller">
                    {{% for u in flota %}}
                    <div class="taller-card search-item" style="border-left: 5px solid {{'var(--danger)' if 'inactiv' in u['ESTADO'].lower() else 'var(--success)'}};">
                        <div class="taller-id">{{{{ u['ID'] }}}}</div>
                        <div class="taller-info">
                            <div class="taller-type">{{{{ u['TIPO'] }}}}</div>
                            <div class="taller-model">{{{{ u['MARCA'] }}}} {{{{ u['MODELO'] }}}}</div>
                            <div class="taller-status">{{{{ u['ESTADO'] }}}}</div>
                        </div>
                    </div>
                    {{% endfor %}}
                </div>
            </div>
        </div>
        <script>
        function filtrarTaller() {{
            var filter = document.getElementById("filtroTaller").value.toUpperCase();
            var items = document.getElementById("listaTaller").getElementsByClassName("search-item");
            for (i = 0; i < items.length; i++) {{
                var txt = items[i].innerText;
                items[i].style.display = txt.toUpperCase().indexOf(filter) > -1 ? "" : "none";
            }}
        }}
        </script>
    </body></html>""", flota=flota, CONF=CONF)

@app.route('/taller/unidad/<id_vehiculo>', methods=['GET', 'POST'])
def taller_unidad(id_vehiculo):
    # MENÚ DE ACCIONES PARA EL MECÁNICO
    return render_template_string(f"""
    <!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">{ESTILO_CSS}</head><body>
        <div class="banner banner-ficha"></div>
        <div class="kiosk-container">
            <div class="kiosk-content">
                <h2 style="color:var(--danger);">PANEL DE UNIDAD</h2>
                <h1 style="font-size:40px; margin:0;">{{{{ id_vehiculo }}}}</h1>
                <p>Seleccione operación a realizar:</p>

                <div style="display:grid; gap:15px; margin-top:20px;">
                    <a href="/operacion/mantenimiento/{{{{ id_vehiculo }}}}" class="big-btn btn-red">🛠️ REPARACIÓN / SOLICITUD</a>
                    <a href="/operacion/combustible/{{{{ id_vehiculo }}}}" class="big-btn btn-orange">⛽ CARGA COMBUSTIBLE</a>
                    <a href="/operacion/fluidos/{{{{ id_vehiculo }}}}" class="big-btn btn-purple">🛢️ CARGA FLUIDOS</a>
                    <a href="/historial/cronograma/{{{{ id_vehiculo }}}}" class="big-btn btn-blue">📅 VER CRONOGRAMA</a>
                </div>
                <br>
                <a href="/taller/mecanico" class="btn-action" style="background:#999;">VOLVER AL LISTADO</a>
            </div>
        </div>
    </body></html>""", id_vehiculo=id_vehiculo, CONF=CONF)

# ==============================================================================
# ✂️  HERRAMIENTA: RECORTADOR INTELIGENTE DE PDF
# ==============================================================================

@app.route('/recortar')
def recortar_pdf():
    # Fecha para el nombre del archivo (formato DD-MM-AA)
    fecha_filename = get_arg_time().strftime("%d-%m-%y")

    return render_template_string("""
    <!DOCTYPE html><html><head>
        <title>Recortador PDF - Obras Públicas</title>
        <meta name="viewport" content="width=device-width,initial-scale=1">
        {{ ESTILO_CSS | safe }}
        <script src="https://unpkg.com/pdf-lib@1.17.1/dist/pdf-lib.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.4.120/pdf.min.js"></script>
    </head><body>
        <div class="container">
            <div class="banner banner-panel"></div>
            <div class="content-padding">
                <div class="admin-header">
                    <div style="font-size:40px;">✂️</div>
                    <div class="titles">
                        <h1 style="margin:0; font-size:28px; color:var(--primary);">RECORTADOR INTELIGENTE</h1>
                        <h2 style="margin:5px 0 0 0; font-size:14px; color:#666;">MUNICIPALIDAD DE FLORENCIO VARELA</h2>
                    </div>
                    <div style="margin-left:auto;">
                        <a href="/" class="btn-action" style="padding:10px 20px; background:#666; text-decoration:none; color:white; border-radius:4px;">⬅ Volver</a>
                    </div>
                </div>

                <div class="kiosk-container" style="max-width:100%; border:2px dashed var(--primary); background:#f9f9f9; padding:40px; text-align:center;">
                    <div id="upload-zone">
                        <span style="font-size:50px; display:block; margin-bottom:20px;">📄</span>
                        <h3 style="color:var(--primary);">Seleccione el PDF a procesar</h3>
                        <p style="color:#666; margin-bottom:25px;">El sistema ajustará cada página al contenido, eliminando los márgenes blancos sobrantes.</p>

                        <input type="file" id="pdf-upload" accept="application/pdf" class="form-input" style="max-width:400px; margin: 0 auto;">
                        <br><br>
                        <button id="process-btn" class="big-btn btn-green" style="max-width:400px; margin: 0 auto;" disabled>PROCESAR Y OPTIMIZAR PDF</button>
                        <div id="status" style="margin-top:20px; font-weight:bold; color:var(--primary); min-height: 24px;"></div>
                    </div>
                </div>
            </div>
        </div>

        <script>
            // IMPORTANTE: Configuración explícita del Worker de PDF.js
            const pdfjsLib = window['pdfjs-dist/build/pdf'];
            pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.4.120/pdf.worker.min.js';

            const { PDFDocument } = PDFLib;
            const fileInput = document.getElementById('pdf-upload');
            const processBtn = document.getElementById('process-btn');
            const status = document.getElementById('status');

            fileInput.onchange = () => {
                processBtn.disabled = !fileInput.files.length;
                status.innerText = fileInput.files.length ? "Archivo listo para procesar." : "";
            };

            processBtn.onclick = async () => {
                const file = fileInput.files[0];
                if (!file) return;

                status.innerText = "⏳ Iniciando proceso...";
                processBtn.disabled = true;

                try {
                    const arrayBuffer = await file.arrayBuffer();

                    // Cargar documento para modificación (pdf-lib)
                    const pdfDoc = await PDFDocument.load(arrayBuffer);
                    const pages = pdfDoc.getPages();

                    // Cargar documento para análisis de imagen (pdf.js)
                    const loadingTask = pdfjsLib.getDocument({data: arrayBuffer});
                    const pdfJS = await loadingTask.promise;

                    for (let i = 0; i < pages.length; i++) {
                        status.innerText = `✂️ Analizando página ${i + 1} de ${pages.length}...`;

                        const pageJS = await pdfJS.getPage(i + 1);
                        const viewport = pageJS.getViewport({ scale: 2.0 }); // Alta resolución para precisión
                        const canvas = document.createElement('canvas');
                        const context = canvas.getContext('2d');
                        canvas.height = viewport.height;
                        canvas.width = viewport.width;

                        const renderContext = { canvasContext: context, viewport: viewport };
                        await pageJS.render(renderContext).promise;

                        const bounds = getBoundingBox(context, canvas.width, canvas.height);

                        if (bounds) {
                            const page = pages[i];
                            const { width, height } = page.getSize();
                            const scaleX = width / canvas.width;
                            const scaleY = height / canvas.height;

                            // Recorte con margen 0
                            const cropWidth = (bounds.right - bounds.left) * scaleX;
                            const cropHeight = (bounds.bottom - bounds.top) * scaleY;
                            const offsetX = (bounds.left * scaleX);
                            const offsetY = (canvas.height - bounds.bottom) * scaleY;

                            page.setMediaBox(offsetX, offsetY, cropWidth, cropHeight);
                            page.setCropBox(offsetX, offsetY, cropWidth, cropHeight);
                        }
                    }

                    status.innerText = "💾 Generando archivo final...";
                    const pdfBytes = await pdfDoc.save();
                    const nombreArchivo = "Informe de Unidades - {{ fecha_filename }}.pdf";

                    download(pdfBytes, nombreArchivo, "application/pdf");
                    status.innerText = "✅ ¡PDF optimizado y descargado!";

                } catch (e) {
                    console.error("Error detallado:", e);
                    status.innerHTML = "<span style='color:red'>❌ Error: " + e.message + "</span>";
                } finally {
                    processBtn.disabled = false;
                }
            };

            function getBoundingBox(ctx, width, height) {
                const imageData = ctx.getImageData(0, 0, width, height).data;
                let top = height, bottom = 0, left = width, right = 0;
                let found = false;

                // Escaneo de píxeles (detecta cualquier cosa que no sea blanco casi puro)
                for (let y = 0; y < height; y++) {
                    for (let x = 0; x < width; x++) {
                        const idx = (y * width + x) * 4;
                        // Umbral de color (250 de 255) para ignorar "ruido" blanco
                        if (imageData[idx] < 250 || imageData[idx+1] < 250 || imageData[idx+2] < 250) {
                            if (x < left) left = x; if (x > right) right = x;
                            if (y < top) top = y; if (y > bottom) bottom = y;
                            found = true;
                        }
                    }
                }
                return found ? { top, bottom, left, right } : null;
            }

            function download(data, filename, type) {
                const file = new Blob([data], { type: type });
                const url = URL.createObjectURL(file);
                const a = document.createElement("a");
                a.href = url; a.download = filename;
                document.body.appendChild(a); a.click();
                setTimeout(() => { document.body.removeChild(a); window.URL.revokeObjectURL(url); }, 0);
            }
        </script>
    </body></html>
    """, ESTILO_CSS=ESTILO_CSS, CONF=CONF, fecha_filename=fecha_filename)

# ==============================================================================
# 🌳  HERRAMIENTA: INFORME JERÁRQUICO DE FLOTA (DIAGRAMA DE ÁRBOL)
# ==============================================================================

CONF["URL_INFORME_ARBOL"] = os.getenv("URL_INFORME_ARBOL", "https://docs.google.com/spreadsheets/d/e/2PACX-1vRU_iWqEQETjf8NcTkqaKsciFQQp7FsEdrdvo-bxH3kN5E87awaHb4oqODO2PgtXN1P5Gl3VGuEtuBl/pub?gid=1643077296&single=true&output=csv")
CONF["URL_INFORME_ARBOL_CONTRATADOS"] = os.getenv("URL_INFORME_ARBOL_CONTRATADOS", "https://docs.google.com/spreadsheets/d/e/2PACX-1vRU_iWqEQETjf8NcTkqaKsciFQQp7FsEdrdvo-bxH3kN5E87awaHb4oqODO2PgtXN1P5Gl3VGuEtuBl/pub?gid=747455468&single=true&output=csv")

import pandas as pd
import json

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

    return render_template_string("""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Informe de Distribución de Flota</title>
        <link rel="icon" type="image/x-icon" href="/icon-muni.ico">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <style>
            @media print {
                .no-print { display: none !important; }
                body { background: white !important; padding: 0 !important; }
                .shadow-sm, .shadow-md { box-shadow: none !important; }
                .page-container { max-width: 100% !important; margin: 0 !important; }
                @page { size: landscape; margin: 8mm; }
            }
            .arrow-line {
                color: #94a3b8;
                font-family: monospace;
                font-weight: bold;
            }
        </style>
    </head>
    <body class="bg-slate-100 min-h-screen p-3 md:p-6 text-slate-800 font-sans">

        <div class="max-w-[1600px] mx-auto space-y-4 page-container">

            <!-- Barra Superior de Botones -->
            <div class="flex flex-wrap items-center justify-end gap-3 no-print">
                <div class="flex items-center gap-2">
                    <button onclick="window.location.reload()" class="inline-flex items-center gap-2 px-4 py-2 bg-sky-600 hover:bg-sky-700 text-white text-xs font-bold rounded-md shadow transition">
                        <i class="fa-solid fa-rotate"></i> Recargar
                    </button>
                    <button onclick="window.print()" class="inline-flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold rounded-md shadow transition">
                        <i class="fa-solid fa-print"></i> Imprimir / Guardar en PDF
                    </button>
                </div>
            </div>

            <!-- Cabecera Principal y Métricas KPI -->
            <div class="bg-white rounded-xl p-5 shadow-sm border border-slate-200">
                <div class="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                    <div class="flex items-center gap-4">
                        <img src="/icon-muni.ico" alt="Logo Municipalidad" class="h-12 w-auto object-contain shrink-0">
                        <div>
                            <div class="flex items-center gap-3">
                                <h1 class="text-2xl font-black text-slate-900 tracking-tight uppercase">ESTADO Y DISTRIBUCIÓN DE PARQUE AUTOMOTOR</h1>
                                <span class="px-3 py-1 bg-slate-900 text-white text-xs font-black rounded-lg shadow-sm tracking-wide">
                                    <i class="fa-regular fa-calendar-days mr-1"></i> {{ fecha_hoy }}
                                </span>
                            </div>
                            <div class="flex items-center gap-2 mt-1">
                                <p class="text-xs font-semibold text-slate-500">Secretaría de Obras, Servicios Públicos, Ambiente y Planificación Urbana</p>
                                <span class="text-slate-300">•</span>
                                <p class="text-[11px] font-medium text-slate-400">
                                    <i class="fa-solid fa-clock-rotate-left mr-0.5 text-slate-400"></i> Última actualización: <span class="font-bold text-slate-600">{{ ultima_actualizacion }}</span>
                                </p>
                            </div>
                        </div>
                    </div>

                    <!-- Cuadros KPI -->
                    <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center min-w-[340px]">
                        <div class="bg-white border border-slate-300 rounded-lg py-2 px-3 shadow-sm">
                            <div id="kpi-total" class="text-2xl font-black text-slate-900 leading-none">0</div>
                            <div class="text-[10px] font-bold text-slate-500 uppercase tracking-wider mt-1">TOTAL FLOTA</div>
                        </div>
                        <div class="bg-white border border-emerald-300 rounded-lg py-2 px-3 shadow-sm">
                            <div id="kpi-activas" class="text-2xl font-black text-emerald-600 leading-none">0</div>
                            <div class="text-[10px] font-bold text-emerald-700 uppercase tracking-wider mt-1">ACTIVAS</div>
                        </div>
                        <div class="bg-white border border-rose-300 rounded-lg py-2 px-3 shadow-sm">
                            <div id="kpi-inactivas" class="text-2xl font-black text-rose-600 leading-none">0</div>
                            <div class="text-[10px] font-bold text-rose-700 uppercase tracking-wider mt-1">INACTIVAS</div>
                        </div>
                        <div class="bg-white border border-sky-300 rounded-lg py-2 px-3 shadow-sm">
                            <div id="kpi-disp" class="text-2xl font-black text-sky-600 leading-none">0%</div>
                            <div class="text-[10px] font-bold text-sky-700 uppercase tracking-wider mt-1">DISPONIBILIDAD</div>
                        </div>
                    </div>
                </div>

                <!-- Panel de Filtros y Controles -->
                <div class="mt-4 pt-4 border-t border-slate-100 space-y-4 no-print">

                    <!-- Barra de Controles Rápidos -->
                    <div class="flex flex-wrap items-center justify-between gap-3 bg-slate-50 p-3 rounded-xl border border-slate-200">
                        <div class="flex flex-wrap items-center gap-2">
                            <button onclick="filtrarSSPP()" class="inline-flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-900 text-white text-xs font-bold rounded-lg shadow-sm transition transform active:scale-95">
                                Solo Áreas SSPP
                            </button>

                            <div class="flex items-center gap-1.5 pl-2 border-l border-slate-300">
                                <span class="text-xs font-bold text-slate-700 uppercase">Origen:</span>
                                <select id="filtro-contratados" onchange="renderizar()" class="bg-white border border-slate-300 text-slate-700 text-xs font-bold rounded-lg px-2.5 py-1.5 focus:ring-sky-500">
                                    <option value="TODAS">Todas (Propias + Contratadas)</option>
                                    <option value="PROPIAS">Solo Propias</option>
                                    <option value="CONTRATADAS">Solo Contratadas</option>
                                </select>
                            </div>
                        </div>

                        <div class="flex items-center gap-1.5">
                            <span class="text-xs font-bold text-slate-700 uppercase">Ordenar por:</span>
                            <select id="filtro-orden" onchange="renderizar()" class="bg-white border border-slate-300 text-slate-700 text-xs font-bold rounded-lg px-2.5 py-1.5 focus:ring-sky-500">
                                <option value="el_nino">Plan El Niño (Maquinarias primero)</option>
                                <option value="alfabetico">Alfabético A-Z</option>
                            </select>
                        </div>
                    </div>

                    <!-- 1. Filtro por Tipos de Unidad -->
                    <div>
                        <div class="flex flex-wrap items-center justify-between gap-2 mb-1.5">
                            <span class="text-xs font-bold uppercase tracking-wider text-slate-700">Filtrar por Tipos:</span>
                            <div class="space-x-3 text-xs">
                                <button onclick="toggleTodosTipos(true)" class="text-sky-600 font-bold hover:underline">Todos</button>
                                <span class="text-slate-300 font-bold">|</span>
                                <button onclick="toggleTodosTipos(false)" class="text-rose-600 font-bold hover:underline">Ninguno</button>
                            </div>
                        </div>
                        <div class="flex flex-wrap gap-2 max-h-32 overflow-y-auto p-1.5 bg-slate-50 rounded-lg border border-slate-200" id="contenedor-filtros-tipo"></div>
                    </div>

                    <!-- 2. Filtro por Áreas -->
                    <div>
                        <div class="flex flex-wrap items-center justify-between gap-2 mb-1.5">
                            <span class="text-xs font-bold uppercase tracking-wider text-slate-700">Filtrar por Áreas:</span>
                            <div class="space-x-3 text-xs">
                                <button onclick="toggleTodasAreas(true)" class="text-sky-600 font-bold hover:underline">Todas</button>
                                <span class="text-slate-300 font-bold">|</span>
                                <button onclick="toggleTodasAreas(false)" class="text-rose-600 font-bold hover:underline">Ningunas</button>
                            </div>
                        </div>
                        <div class="flex flex-wrap gap-2 max-h-32 overflow-y-auto p-1.5 bg-slate-50 rounded-lg border border-slate-200" id="contenedor-filtros-area"></div>
                    </div>

                </div>
            </div>

            <!-- Contenedor del Diagrama de Árbol -->
            <div id="arbol-container" class="space-y-3">
                <!-- Se llena dinámicamente con JavaScript -->
            </div>

        </div>

        <script>
            const rawData = {{ rawData_json|safe }};
            const areasDisponibles = {{ areas_json|safe }};
            const tiposDisponibles = {{ tipos_json|safe }};

            const termsSSPP = ['ALUMBRADO', 'HIGIENE URBANA', 'EQUIPOS VIALES', 'CEMENTERIO', 'ESPACIOS VERDES', 'ALLAN', 'BOSQUES'];
            const ordenElNino = ["EXCAVADORA", "RETROEXCAVADORA", "PALA CARGADORA", "MINICARGADORA", "CAMION VOLCADOR", "CAMIÓN VOLCADOR", "CAMION TRACTOR", "CAMIÓN TRACTOR", "TRACTOR", "CAMION HIDROELEVADOR", "CAMIÓN HIDROELEVADOR", "CAMIONETA", "MOTONIVELADORA"];

            let areasSeleccionadas = new Set(areasDisponibles);
            let tiposSeleccionados = new Set(tiposDisponibles);

            function inicializarFiltros() {
                const contTipo = document.getElementById('contenedor-filtros-tipo');
                contTipo.innerHTML = '';
                tiposDisponibles.forEach(tipo => {
                    const label = document.createElement('label');
                    label.className = 'inline-flex items-center gap-1.5 px-2.5 py-1 bg-white hover:bg-slate-100 rounded text-xs font-semibold cursor-pointer border border-slate-200 select-none transition';

                    const check = document.createElement('input');
                    check.type = 'checkbox';
                    check.value = tipo;
                    check.checked = true;
                    check.className = 'rounded text-slate-800 focus:ring-slate-500 tipo-checkbox cursor-pointer';
                    check.onchange = (e) => {
                        if (e.target.checked) tiposSeleccionados.add(tipo);
                        else tiposSeleccionados.delete(tipo);
                        renderizar();
                    };

                    label.appendChild(check);
                    label.appendChild(document.createTextNode(tipo));
                    contTipo.appendChild(label);
                });

                const contArea = document.getElementById('contenedor-filtros-area');
                contArea.innerHTML = '';
                areasDisponibles.forEach(area => {
                    const label = document.createElement('label');
                    label.className = 'inline-flex items-center gap-1.5 px-2.5 py-1 bg-white hover:bg-slate-100 rounded text-xs font-semibold cursor-pointer border border-slate-200 select-none transition';

                    const check = document.createElement('input');
                    check.type = 'checkbox';
                    check.value = area;
                    check.checked = true;
                    check.className = 'rounded text-sky-600 focus:ring-sky-500 area-checkbox cursor-pointer';
                    check.onchange = (e) => {
                        if (e.target.checked) areasSeleccionadas.add(area);
                        else areasSeleccionadas.delete(area);
                        renderizar();
                    };

                    label.appendChild(check);
                    label.appendChild(document.createTextNode(area));
                    contArea.appendChild(label);
                });
            }

            function toggleTodosTipos(s) {
                const checks = document.querySelectorAll('.tipo-checkbox');
                tiposSeleccionados.clear();
                checks.forEach(c => {
                    c.checked = s;
                    if (s) tiposSeleccionados.add(c.value);
                });
                renderizar();
            }

            function toggleTodasAreas(s) {
                const checks = document.querySelectorAll('.area-checkbox');
                areasSeleccionadas.clear();
                checks.forEach(c => {
                    c.checked = s;
                    if (s) areasSeleccionadas.add(c.value);
                });
                renderizar();
            }

            function filtrarSSPP() {
                areasSeleccionadas.clear();
                const checks = document.querySelectorAll('.area-checkbox');
                checks.forEach(c => {
                    const valUpper = c.value.toUpperCase();
                    const match = termsSSPP.some(t => valUpper.includes(t));
                    c.checked = match;
                    if (match) areasSeleccionadas.add(c.value);
                });
                renderizar();
            }

            function renderizar() {
                const elOrigen = document.getElementById('filtro-contratados');
                const modoOrigen = elOrigen ? elOrigen.value : 'TODAS';
                const elOrden = document.getElementById('filtro-orden');
                const modoOrden = elOrden ? elOrden.value : 'el_nino';

                const filtrados = rawData.filter(u => {
                    const cTipo = tiposSeleccionados.has(u.TIPO);
                    const cArea = areasSeleccionadas.has(u.AREA);
                    let cOrig = true;
                    if (modoOrigen === 'PROPIAS') cOrig = !u.CONTRATADO;
                    else if (modoOrigen === 'CONTRATADAS') cOrig = u.CONTRATADO;
                    return cTipo && cArea && cOrig;
                });

                const total = filtrados.length;
                const activas = filtrados.filter(u => u.ESTADO_CAT === 'ACTIVAS').length;
                const inactivas = total - activas;
                const disp = total > 0 ? ((activas / total) * 100).toFixed(1) : 0;

                document.getElementById('kpi-total').textContent = total;
                document.getElementById('kpi-activas').textContent = activas;
                document.getElementById('kpi-inactivas').textContent = inactivas;
                document.getElementById('kpi-disp').textContent = `${disp}%`;

                const container = document.getElementById('arbol-container');
                container.innerHTML = '';

                if (total === 0) {
                    container.innerHTML = `<div class="bg-white rounded-xl p-10 text-center text-slate-400 font-bold border border-slate-200">No hay unidades que coincidan con los filtros seleccionados.</div>`;
                    return;
                }

                // Estructura jerárquica unificada: TIPO -> ESTADO -> ÁREA -> RESUMEN
                const tree = {};
                filtrados.forEach(u => {
                    if (!tree[u.TIPO]) tree[u.TIPO] = { total: 0, estados: { 'ACTIVAS': {}, 'INACTIVAS': {} } };
                    tree[u.TIPO].total++;

                    const est = u.ESTADO_CAT;
                    if (!tree[u.TIPO].estados[est][u.AREA]) {
                        tree[u.TIPO].estados[est][u.AREA] = {};
                    }

                    let resNorm = (u.RESUMEN || 'Sin resumen especificado').trim().replace(/\\s+/g, ' ');
                    if (u.PRESTAMO && /^de pr[eé]stamo\\s+/i.test(resNorm)) {
                        resNorm = resNorm.replace(/^de pr[eé]stamo\\s+/i, '');
                    }
                    const groupKey = (u.CONTRATADO ? 'CONTRATADO:' : 'PROPIA:') + resNorm;
                    if (!tree[u.TIPO].estados[est][u.AREA][groupKey]) {
                        tree[u.TIPO].estados[est][u.AREA][groupKey] = [];
                    }
                    tree[u.TIPO].estados[est][u.AREA][groupKey].push(u);
                });

                let listaTipos = Object.keys(tree);
                if (modoOrden === 'el_nino') {
                    listaTipos.sort((a, b) => {
                        const idxA = ordenElNino.findIndex(item => a.includes(item) || item.includes(a));
                        const idxB = ordenElNino.findIndex(item => b.includes(item) || item.includes(b));
                        const rankA = idxA !== -1 ? idxA : 999;
                        const rankB = idxB !== -1 ? idxB : 999;
                        if (rankA !== rankB) return rankA - rankB;
                        return a.localeCompare(b);
                    });
                } else {
                    listaTipos.sort((a, b) => a.localeCompare(b));
                }

                listaTipos.forEach(tipo => {
                    const tipoData = tree[tipo];

                    const card = document.createElement('div');
                    card.className = 'bg-white rounded-xl p-3 md:p-4 shadow-sm border border-slate-200 flex flex-col md:flex-row md:items-center gap-4';

                    let leftCol = `
                        <div class="w-full md:w-60 flex-shrink-0">
                            <div class="flex items-center gap-2 border-2 border-slate-900 rounded-lg p-1.5 bg-white shadow-sm">
                                <span class="bg-slate-900 text-white font-black text-sm px-2.5 py-1 rounded min-w-[28px] text-center">${tipoData.total}</span>
                                <span class="font-black text-xs text-slate-900 tracking-wide uppercase leading-tight truncate" title="${tipo}">${tipo}</span>
                            </div>
                        </div>
                    `;

                    let rightCol = `<div class="flex-1 space-y-3 flex flex-col justify-center">`;

                    ['ACTIVAS', 'INACTIVAS'].forEach(estadoKey => {
                        const areasObj = tipoData.estados[estadoKey];
                        const cantEstado = Object.values(areasObj).reduce((acc, curr) => {
                            return acc + Object.values(curr).reduce((sum, unids) => sum + unids.length, 0);
                        }, 0);

                        if (cantEstado > 0) {
                            const isActiva = estadoKey === 'ACTIVAS';
                            const badgeBg = isActiva ? 'bg-emerald-600' : 'bg-rose-600';
                            const badgeTextColor = isActiva ? 'text-emerald-800' : 'text-rose-800';

                            rightCol += `
                                <div class="flex flex-wrap md:flex-nowrap items-start gap-2 text-xs">
                                    <div class="flex items-center gap-1.5 w-32 flex-shrink-0 mt-0.5">
                                        <span class="arrow-line">→</span>
                                        <span class="px-2 py-0.5 rounded text-white font-black ${badgeBg} text-[11px]">${cantEstado}</span>
                                        <span class="font-black ${badgeTextColor} tracking-wide text-[11px]">${estadoKey}</span>
                                    </div>
                                    <div class="flex-1 space-y-2 pl-1">
                            `;

                            Object.keys(areasObj).sort().forEach(area => {
                                const resumenesObj = areasObj[area];
                                const cantArea = Object.values(resumenesObj).reduce((sum, unids) => sum + unids.length, 0);
                                const areaBorder = isActiva ? 'border-emerald-300 bg-emerald-50/60 text-emerald-900' : 'border-rose-300 bg-rose-50/60 text-rose-900';

                                rightCol += `
                                    <div class="flex flex-wrap md:flex-nowrap items-start gap-2">
                                        <div class="flex items-center gap-1.5 border px-2 py-0.5 rounded text-[11px] font-bold ${areaBorder} w-[210px] min-w-[210px] flex-shrink-0 mt-0.5">
                                            <span class="arrow-line">→</span>
                                            <span class="font-black">${cantArea}</span>
                                            <span class="truncate">${area}</span>
                                        </div>
                                        <div class="flex flex-col gap-1.5 flex-1 min-w-0">
                                `;

                                Object.keys(resumenesObj).sort().forEach(groupKey => {
                                    const itemsUnidad = resumenesObj[groupKey];
                                    const cantGroup = itemsUnidad.length;
                                    const tieneContratados = itemsUnidad.some(i => i.CONTRATADO);
                                    const tienePrestamos = itemsUnidad.some(i => i.PRESTAMO);

                                    const resumenDisplay = groupKey.replace(/^(CONTRATADO|PROPIA):/, '');

                                    let nombresUnidadesStr = "";
                                    if (tieneContratados) {
                                        nombresUnidadesStr = cantGroup > 1 ? `${cantGroup} Contratadas` : 'Contratada';
                                    } else {
                                        nombresUnidadesStr = itemsUnidad.map(i => i.UNIDAD).join(', ');
                                    }

                                    const resBoxStyle = isActiva
                                        ? 'bg-emerald-50 text-emerald-900 border-emerald-200'
                                        : 'bg-rose-50 text-rose-900 border-rose-200';

                                    let contratadoBadge = tieneContratados ? `<span class="inline-flex items-center gap-1 px-1.5 py-0.2 bg-indigo-100 text-indigo-800 border border-indigo-300 rounded font-bold text-[10px] uppercase">CONTRATADO</span>` : '';
                                    let prestamoBadge = tienePrestamos ? `<span class="inline-flex items-center gap-1 px-1.5 py-0.2 bg-amber-100 text-amber-800 border border-amber-300 rounded font-bold text-[10px] uppercase">DE PRÉSTAMO</span>` : '';

                                    rightCol += `
                                        <div class="flex items-center flex-wrap md:flex-nowrap gap-1 border px-2 py-0.5 rounded text-[11px] font-medium ${resBoxStyle} w-full">
                                            <span class="arrow-line">→</span>
                                            <span class="font-black">${cantGroup}</span>
                                            ${contratadoBadge}
                                            ${prestamoBadge}
                                            <span class="font-bold">${resumenDisplay}</span>
                                            <span class="text-[10px] text-slate-500 font-semibold">(${nombresUnidadesStr})</span>
                                        </div>
                                    `;
                                });

                                rightCol += `</div></div>`;
                            });

                            rightCol += `</div></div>`;
                        }
                    });

                    rightCol += `</div>`;
                    card.innerHTML = leftCol + rightCol;
                    container.appendChild(card);
                });
            }

            document.addEventListener('DOMContentLoaded', () => {
                inicializarFiltros();
                renderizar();
            });
        </script>
    </body>
    </html>
    """,
    fecha_hoy=fecha_hoy,
    ultima_actualizacion=ultima_actualizacion,
    rawData_json=json.dumps(unidades_lista, ensure_ascii=False),
    areas_json=json.dumps(areas_disponibles, ensure_ascii=False),
    tipos_json=json.dumps(tipos_disponibles, ensure_ascii=False))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')