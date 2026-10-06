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
    print("=== INICIANDO PRUEBAS DEL PIPELINE SQLITE + DATAGRID ===")
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
    assert "/informe/arbol" in html
    print("  ✓ Ruta / funciona y contiene la barra de herramientas y enlace a planilla.")

    # 2. Test admin/planilla
    print("\n2. Probando ruta /admin/planilla (Tabulator data grid)")
    res = client.get('/admin/planilla')
    assert res.status_code == 200, f"Error en /admin/planilla: {res.status_code}"
    html = res.data.decode('utf-8')
    assert "PLANILLA DE GESTIÓN Y EDICIÓN DE FLOTA" in html
    assert "tabulator-tables" in html
    assert "fleetData" in html
    print("  ✓ Ruta /admin/planilla renderiza correctamente con Tabulator.js.")

    # 3. Test ficha técnica y especificaciones NoSQL
    print("\n3. Probando ruta /ficha/AE-1 (Especificaciones NoSQL dinámicas)")
    res = client.get('/ficha/AE-1')
    assert res.status_code == 200, f"Error en /ficha/AE-1: {res.status_code}"
    html = res.data.decode('utf-8')
    assert "AE-1" in html
    v = db.find_vehicle_by_id('AE-1')
    assert v is not None, "Unidad AE-1 no encontrada en SQLite"
    print(f"  Unidad AE-1 encontrada: {v['MARCA']} {v['MODELO']}")
    print(f"  Especificaciones NoSQL dinámicas de AE-1: {v.get('ESPECIFICACIONES', {})}")
    assert isinstance(v.get('ESPECIFICACIONES'), dict)
    print("  ✓ Ficha técnica renderiza y extrae solo especificaciones dinámicas pobladas.")

    # 4. Test informe de árbol
    print("\n4. Probando ruta /informe/arbol (Diagrama jerárquico desde SQLite)")
    res = client.get('/informe/arbol')
    assert res.status_code == 200, f"Error en /informe/arbol: {res.status_code}"
    html = res.data.decode('utf-8')
    assert "rawData" in html and "ESTADO Y DISTRIBUCIÓN DE PARQUE AUTOMOTOR" in html
    print("  ✓ /informe/arbol renderiza velozmente desde SQLite.")

    # 5. Test edición en vivo vía API: /api/vehiculo/actualizar
    print("\n5. Probando API /api/vehiculo/actualizar (Guardado en celda editable)")
    test_diag = "Prueba automatizada de guardado en vivo"
    res = client.post('/api/vehiculo/actualizar', json={
        'id': 'AE-1',
        'campo': 'diagnostico',
        'valor': test_diag
    })
    assert res.status_code == 200, f"Error en api: {res.status_code}"
    json_data = res.get_json()
    assert json_data.get('success') is True, f"Fallo al actualizar: {json_data}"
    
    # Verificar cambio en DB
    v_updated = db.find_vehicle_by_id('AE-1')
    assert v_updated['DIAGNÓSTICO'] == test_diag, f"Valor en DB: {v_updated['DIAGNÓSTICO']}"
    print("  ✓ Celda actualizada y persistida correctamente en SQLite.")

    # 6. Test registro de actividad (reemplazo de CSV)
    print("\n6. Probando registro de actividad en SQLite (reemplaza historial_actividad.csv)")
    res = client.post('/operacion/actividad/AE-1', data={
        'accion': 'SALIDA',
        'motivo': 'Prueba test bot'
    }, follow_redirects=True)
    assert res.status_code == 200
    hist = db.get_history_records('actividad', 'AE-1')
    assert len(hist) > 0, "No se registraron actividades en SQLite"
    assert hist[0]['ACCION'] == 'SALIDA'
    assert hist[0]['MOTIVO'] == 'Prueba test bot'
    print(f"  ✓ Registro guardado en SQLite con éxito: {hist[0]}")

    # 7. Test historial visualización: /historial/actividad/AE-1
    print("\n7. Probando ruta /historial/actividad/AE-1")
    res = client.get('/historial/actividad/AE-1')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert "Prueba test bot" in html
    print("  ✓ Historial lee directamente de SQLite y renderiza registros.")

    # 8. Test exportar Excel
    print("\n8. Probando exportación a Excel /admin/exportar/excel")
    res = client.get('/admin/exportar/excel')
    assert res.status_code == 200
    assert "spreadsheetml" in res.content_type
    print(f"  ✓ Excel exportado correctamente: {len(res.data)} bytes generados.")

    print("\n=== TODAS LAS PRUEBAS COMPLETADAS CON ÉXITO ===")

if __name__ == '__main__':
    run_tests()
