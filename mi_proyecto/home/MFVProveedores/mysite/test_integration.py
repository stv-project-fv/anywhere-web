import sys
import os

# Forzar encoding UTF-8 en stdout de Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# Asegurar path
sys.path.insert(0, os.path.abspath("mi_proyecto/home/MFVProveedores/mysite"))

from flask_app import app
import db_service as db

def run_tests():
    print("=== INICIANDO PRUEBAS DEL SISTEMA: TALLER, OTS Y PIPELINE SQLITE ===")
    app.config['TESTING'] = True
    app.config['SECRET_KEY'] = 'test_secret'
    client = app.test_client()

    with client.session_transaction() as sess:
        sess['panel_logged_in'] = True
        sess['admin_logged_in'] = True

    # 1. Test index
    print("\n1. Probando ruta principal / (Index con sesión)")
    res = client.get('/')
    assert res.status_code == 200, f"Error en /: {res.status_code}"
    html = res.data.decode('utf-8')
    assert "PANEL DE FLOTA" in html
    assert "Sincronizar Google Sheets" in html
    assert "/admin/planilla" in html
    assert "/taller" in html
    assert "/informe/arbol" in html
    print("  ✓ Ruta / funciona y contiene la barra de herramientas y enlace a /taller.")

    # 2. Test admin/planilla
    print("\n2. Probando ruta /admin/planilla (Tabulator data grid)")
    res = client.get('/admin/planilla')
    assert res.status_code == 200, f"Error en /admin/planilla: {res.status_code}"
    html = res.data.decode('utf-8')
    assert "PLANILLA DE GESTIÓN Y EDICIÓN DE FLOTA" in html
    assert "tabulator-tables" in html
    assert "fleetData" in html
    assert "/taller" in html
    print("  ✓ Ruta /admin/planilla renderiza correctamente con enlace a taller.")

    # 3. Test ficha técnica y especificaciones NoSQL
    print("\n3. Probando ruta /ficha/AE-1")
    res = client.get('/ficha/AE-1')
    assert res.status_code == 200, f"Error en /ficha/AE-1: {res.status_code}"
    html = res.data.decode('utf-8')
    assert "AE-1" in html
    v = db.find_vehicle_by_id('AE-1')
    assert v is not None, "Unidad AE-1 no encontrada en SQLite"
    print(f"  Unidad AE-1 encontrada: {v['MARCA']} {v['MODELO']}")
    print("  ✓ Ficha técnica renderiza correctamente.")

    # 4. Test informe de árbol
    print("\n4. Probando ruta /informe/arbol")
    res = client.get('/informe/arbol')
    assert res.status_code == 200, f"Error en /informe/arbol: {res.status_code}"
    html = res.data.decode('utf-8')
    assert "rawData" in html
    print("  ✓ /informe/arbol renderiza velozmente desde SQLite.")

    # 5. Test edición en vivo vía API: /api/vehiculo/actualizar
    print("\n5. Probando API /api/vehiculo/actualizar")
    test_diag = "Prueba de celda viva"
    res = client.post('/api/vehiculo/actualizar', json={
        'id': 'AE-1',
        'campo': 'diagnostico',
        'valor': test_diag
    })
    assert res.status_code == 200
    v_updated = db.find_vehicle_by_id('AE-1')
    assert v_updated['DIAGNÓSTICO'] == test_diag
    print("  ✓ Celda actualizada y persistida correctamente en SQLite.")

    # 6. Test PANEL DE TALLER (/taller)
    print("\n6. Probando Panel Operativo de Taller (/taller)")
    res = client.get('/taller')
    assert res.status_code == 200, f"Error en /taller: {res.status_code}"
    html = res.data.decode('utf-8')
    assert "TALLER MUNICIPAL - ÓRDENES DE TRABAJO" in html
    assert "INGRESAR UNIDAD AL TALLER" in html
    print("  ✓ /taller renderiza el panel institucional para operarios.")

    # 7. Test CICLO COMPLETO DE ORDEN DE TRABAJO (OT)
    print("\n7. Probando Ciclo de Vida de Órdenes de Trabajo (OT) con impacto en flota:")
    
    # a. Apertura de OT -> Pasa a EN REPARACIÓN
    res_crear = client.post('/taller/ot/crear', data={
        'vehiculo_id': 'AE-1',
        'motivo_ingreso': 'Falla hidráulica en circuito de levante',
        'sistema_afectado': 'HIDRAULICA',
        'prioridad': 'URGENTE',
        'mecanico_asignado': 'J. Gómez',
        'km_ingreso': '125400'
    }, follow_redirects=True)
    assert res_crear.status_code == 200
    
    v_taller = db.find_vehicle_by_id('AE-1')
    assert v_taller['ESTADO'] == 'EN REPARACIÓN', f"Estado esperado EN REPARACIÓN, obtenido: {v_taller['ESTADO']}"
    assert "OT #" in v_taller['DIAGNÓSTICO']
    print(f"  ✓ Apertura de OT: Unidad AE-1 pasó automáticamente a '{v_taller['ESTADO']}' con diagnóstico '{v_taller['DIAGNÓSTICO']}'.")

    # b. Comprobar que /ficha/AE-1 exhibe la alerta institucional de taller
    res_ficha_ot = client.get('/ficha/AE-1')
    assert res_ficha_ot.status_code == 200
    html_ficha = res_ficha_ot.data.decode('utf-8')
    assert "UNIDAD EN TALLER MECÁNICO" in html_ficha
    assert "Falla hidráulica" in html_ficha
    print("  ✓ Ficha técnica muestra la advertencia institucional de unidad en taller.")

    # c. Obtener OT activa y solicitar repuesto
    ot_activa = db.get_ot_activa_vehiculo('AE-1')
    assert ot_activa is not None
    ot_id = ot_activa['id']
    ot_num = ot_activa['numero_ot']
    
    res_rep = client.post(f'/taller/ot/{ot_id}/estado', data={
        'accion': 'REPUESTO',
        'repuestos_detalle': 'Retén de 2 pulgadas y flexible alta presión'
    }, follow_redirects=True)
    assert res_rep.status_code == 200
    
    ot_mod = db.get_ot_by_id(ot_id)
    assert ot_mod['estado_ot'] == 'ESPERANDO_REPUESTO'
    assert ot_mod['repuestos_detalle'] == 'Retén de 2 pulgadas y flexible alta presión'
    v_rep = db.find_vehicle_by_id('AE-1')
    assert "ESPERANDO REPUESTO" in v_rep['DIAGNÓSTICO']
    print(f"  ✓ Solicitud de repuesto: OT pasó a '{ot_mod['estado_ot']}' e impactó en diagnóstico global.")

    # d. Alta operativa (Cierre de OT) -> Retorno a ACTIVO
    res_cerrar = client.post(f'/taller/ot/{ot_id}/cerrar', data={
        'trabajo_realizado': 'Circuito reemplazado, sellos nuevos y purga completa',
        'km_egreso': '125410'
    }, follow_redirects=True)
    assert res_cerrar.status_code == 200

    v_activo = db.find_vehicle_by_id('AE-1')
    assert v_activo['ESTADO'] == 'ACTIVO', f"Estado esperado ACTIVO, obtenido: {v_activo['ESTADO']}"
    assert v_activo['DIAGNÓSTICO'] == ''
    print(f"  ✓ Alta operativa: Unidad AE-1 retornó automáticamente a '{v_activo['ESTADO']}' y limpió diagnóstico temporal.")

    # 8. Test PRESERVACIÓN DE HISTORIALES (/historial/*)
    print("\n8. Probando preservación de los 4 accesos de /historial:")

    # a. Historial Mantenimiento (Debe incluir la OT cerrada)
    res_hist_mant = client.get('/historial/mantenimiento/AE-1')
    assert res_hist_mant.status_code == 200
    html_mant = res_hist_mant.data.decode('utf-8')
    assert "HISTORIAL DE REPARACIONES" in html_mant
    assert ot_num in html_mant
    assert "Circuito reemplazado" in html_mant
    print("  ✓ /historial/mantenimiento/AE-1 integra la OT cerrada con sus tareas y repuestos.")

    # b. Historial Imágenes (Legajo fotográfico oficial, no espacio nulo)
    res_hist_img = client.get('/historial/imagenes/AE-1')
    assert res_hist_img.status_code == 200
    html_img = res_hist_img.data.decode('utf-8')
    assert "LEGAJO FOTOGRÁFICO" in html_img
    assert "AE-1" in html_img
    print("  ✓ /historial/imagenes/AE-1 renderiza el legajo fotográfico oficial de la unidad.")

    # c. Historial Ingresos
    res_hist_ing = client.get('/historial/ingresos/AE-1')
    assert res_hist_ing.status_code == 200
    html_ing = res_hist_ing.data.decode('utf-8')
    assert "CONTROL DE INGRESOS" in html_ing
    print("  ✓ /historial/ingresos/AE-1 responde HTTP 200 y renderiza vista formal.")

    # d. Historial Cronograma
    res_hist_cron = client.get('/historial/cronograma/AE-1')
    assert res_hist_cron.status_code == 200
    html_cron = res_hist_cron.data.decode('utf-8')
    assert "CRONOGRAMA PREVENTIVO" in html_cron
    print("  ✓ /historial/cronograma/AE-1 responde HTTP 200 y renderiza vista formal.")

    # 9. Test eliminación de circuitos obsoletos
    print("\n9. Probando desmantelamiento de rutas obsoletas de kiosco:")
    res_kiosk = client.get('/puesto/actividad')
    assert res_kiosk.status_code == 404, f"Esperaba 404 para /puesto/actividad, obtenido {res_kiosk.status_code}"
    
    res_op = client.get('/operacion/actividad/AE-1')
    assert res_op.status_code == 404, f"Esperaba 404 para /operacion/actividad, obtenido {res_op.status_code}"

    res_taller_leg = client.get('/taller/mecanico')
    assert res_taller_leg.status_code == 404, f"Esperaba 404 para /taller/mecanico, obtenido {res_taller_leg.status_code}"

    res_adm_taller = client.get('/admin/taller')
    assert res_adm_taller.status_code == 302, f"Esperaba 302 redirigiendo a /taller, obtenido {res_adm_taller.status_code}"
    print("  ✓ Rutas obsoletas de kiosco eliminadas; /admin/taller redirige a /taller.")

    # 10. Test exportar Excel y restricciones
    print("\n10. Probando exportación Excel y reglas de negocio:")
    res_excel = client.get('/admin/exportar/excel')
    assert res_excel.status_code == 200
    assert "spreadsheetml" in res_excel.content_type

    # Bloqueo patente
    res_patente = client.post('/api/vehiculo/actualizar', json={'id': 'AE-1', 'campo': 'dominio', 'valor': 'BLOQUEO'})
    assert res_patente.get_json().get('success') is False
    print("  ✓ Excel y reglas de negocio preservadas sin regresión.")

    print("\n=== TODAS LAS PRUEBAS COMPLETADAS CON ÉXITO (100% OK) ===")

if __name__ == '__main__':
    run_tests()
