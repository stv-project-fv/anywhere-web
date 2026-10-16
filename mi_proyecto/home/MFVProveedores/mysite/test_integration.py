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
from models import OrdenTrabajo, Vehiculo, MetadataSync, AvanceOT, RepuestoOT, RegistroMantenimiento

def run_tests():
    print("=== INICIANDO PRUEBAS DEL SISTEMA: TALLER OPERARIO, SEGUIMIENTO ADMIN Y REPUESTOS ===")
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
    assert "EN REPARACIÓN" in html
    assert "/taller" in html
    print("  ✓ Ruta /admin/planilla renderiza correctamente con enlace a taller y estados completos.")

    # 3. Test ficha técnica y especificaciones NoSQL
    print("\n3. Probando ruta /ficha/AE-1")
    res = client.get('/ficha/AE-1')
    assert res.status_code == 200, f"Error en /ficha/AE-1: {res.status_code}"
    html = res.data.decode('utf-8')
    assert "AE-1" in html
    v = db.find_vehicle_by_id('AE-1')
    assert v is not None, "Unidad AE-1 no encontrada en SQLite"
    assert 'ANIO' in v and 'AÑO' in v, "Falta simetría en alias de año"
    assert 'DIAGNOSTICO' in v and 'DIAGNÓSTICO' in v, "Falta simetría en alias de diagnóstico"

    # Verificar serialización de MetadataSync
    m_sync = MetadataSync(id=1, estado_sync='COMPLETADO', ultima_sincronizacion='07/10/2026 15:00:00')
    m_dict = m_sync.to_dict()
    assert m_dict['estado_sync'] == 'COMPLETADO'
    assert m_dict['ultima_sincronizacion'] == '07/10/2026 15:00:00'

    # Verificar badge 'st-bad' cuando el estado es 'irrecuperable'
    v_orig_estado = v['ESTADO']
    db.update_vehicle_cell('AE-1', 'estado', 'IRRECUPERABLE')
    res_irr = client.get('/ficha/AE-1')
    assert "st-bad" in res_irr.data.decode('utf-8'), "Unidad irrecuperable debe mostrar badge st-bad"
    db.update_vehicle_cell('AE-1', 'estado', v_orig_estado)

    print(f"  Unidad AE-1 encontrada: {v['MARCA']} {v['MODELO']}")
    print("  ✓ Ficha técnica, alias simétricos, MetadataSync y badge irrecuperable renderizan correctamente.")

    # 4. Test informe de árbol
    print("\n4. Probando ruta /informe/arbol")
    res = client.get('/informe/arbol')
    assert res.status_code == 200, f"Error en /informe/arbol: {res.status_code}"
    html = res.data.decode('utf-8')
    assert "rawData" in html
    print("  ✓ /informe/arbol renderiza velozmente desde SQLite.")

    # 5. Test edición en vivo vía API: /api/vehiculo/actualizar
    print("\n5. Probando API /api/vehiculo/actualizar")
    # Probar bloqueo de identificadores inmutables
    res_id = client.post('/api/vehiculo/actualizar', json={'id': 'AE-1', 'campo': 'id', 'valor': 'AE-99'})
    assert res_id.get_json()['success'] is False, "El id no debe ser editable"
    res_uni = client.post('/api/vehiculo/actualizar', json={'id': 'AE-1', 'campo': 'unidad', 'valor': 'AE-99'})
    assert res_uni.get_json()['success'] is False, "La unidad no debe ser editable"

    # Probar persistencia de columnas estructurales
    res_marca = client.post('/api/vehiculo/actualizar', json={'id': 'AE-1', 'campo': 'marca', 'valor': 'hangcha'})
    assert res_marca.get_json()['success'] is True
    res_anio = client.post('/api/vehiculo/actualizar', json={'id': 'AE-1', 'campo': 'anio', 'valor': '2023'})
    assert res_anio.get_json()['success'] is True

    test_diag = "Prueba de celda viva"
    res = client.post('/api/vehiculo/actualizar', json={
        'id': 'AE-1',
        'campo': 'diagnostico',
        'valor': test_diag
    })
    assert res.status_code == 200
    v_updated = db.find_vehicle_by_id('AE-1')
    assert v_updated['DIAGNÓSTICO'] == test_diag
    assert v_updated['MARCA'] == 'HANGCHA'
    assert v_updated['ANIO'] == '2023'
    print("  ✓ Celda actualizada, columnas estructurales mapeadas y bloqueo de ID verificado en SQLite.")

    # 6. Test PANEL DE TALLER OPERARIO (/taller) y PANEL ADMIN (/admin/taller)
    print("\n6. Probando paneles separados:")
    res_taller = client.get('/taller')
    assert res_taller.status_code == 200, f"Error en /taller: {res_taller.status_code}"
    html_taller = res_taller.data.decode('utf-8')
    assert "PANEL DE TALLER - PISO DE GALPÓN" in html_taller
    assert "INGRESAR UNIDAD" in html_taller
    assert 'href="/admin/taller"' not in html_taller, "Panel de operario no debe tener link a /admin/taller"
    assert 'href="/"' not in html_taller, "Panel de operario no debe tener link al panel general /"
    print("  ✓ /taller renderiza el panel para operarios de galpón (aislado).")

    res_admin_taller = client.get('/admin/taller')
    assert res_admin_taller.status_code == 200, f"Error en /admin/taller: {res_admin_taller.status_code}"
    html_admin = res_admin_taller.data.decode('utf-8')
    assert "SEGUIMIENTO Y GESTIÓN DE TALLER" in html_admin
    assert "GESTIÓN DE COMPRAS Y REPUESTOS" in html_admin
    assert 'href="/taller"' not in html_admin, "Panel administrativo no debe tener link a /taller"
    assert 'href="/"' in html_admin, "Panel administrativo debe conservar acceso al panel general"
    print("  ✓ /admin/taller renderiza el panel administrativo de seguimiento y compras (aislado).")

    # 7. Test CICLO DE VIDA DE ORDEN DE TRABAJO (OT), AVANCES Y REPUESTOS
    print("\n7. Probando ciclo completo de OT con avances secuenciales y repuestos diferenciados:")
    
    # Asegurar estado limpio cerrando todas las OTs previas de prueba para AE-1
    session_clean = db.get_session()
    for po in session_clean.query(OrdenTrabajo).filter(OrdenTrabajo.vehiculo_id == 'AE-1', OrdenTrabajo.estado_ot != 'CERRADA').all():
        po.estado_ot = 'CERRADA'
    v_clean = session_clean.query(Vehiculo).filter_by(id='AE-1').first()
    if v_clean:
        v_clean.estado = 'ACTIVO'
        v_clean.diagnostico = ''
    session_clean.commit()
    session_clean.close()

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
    
    ot_activa = db.get_ot_activa_vehiculo('AE-1')
    assert ot_activa is not None
    ot_id = ot_activa['id']
    ot_num = ot_activa['numero_ot']
    
    v_taller = db.find_vehicle_by_id('AE-1')
    assert v_taller['ESTADO'] == 'EN REPARACIÓN'
    print(f"  ✓ Apertura de OT: Unidad AE-1 en 'EN REPARACIÓN' con número {ot_num}.")

    # b. Registro de avances secuenciales con fecha y hora
    res_av1 = client.post(f'/taller/ot/{ot_id}/avance', data={
        'descripcion': 'Desmontaje de bomba hidráulica y revisión de plato de válvulas',
        'mecanico': 'J. Gómez'
    }, follow_redirects=True)
    assert res_av1.status_code == 200

    res_av2 = client.post(f'/taller/ot/{ot_id}/avance', data={
        'descripcion': 'Limpieza de cárter y prueba de presión en banco',
        'mecanico': 'M. Silva'
    }, follow_redirects=True)
    assert res_av2.status_code == 200

    avances = db.get_avances_ot(ot_id)
    assert len(avances) >= 3  # Avance inicial de ingreso + 2 manuales
    assert "Desmontaje de bomba hidráulica" in avances[1]['descripcion']
    assert "Limpieza de cárter" in avances[2]['descripcion']
    print(f"  ✓ Avances secuenciales registrados con fecha, hora y mecánico ({len(avances)} registrados).")

    # c. Operario solicita 2 repuestos por ítem (estado inicial: SOLICITADO, incluyendo comillas simples)
    res_rep1 = client.post(f'/taller/ot/{ot_id}/repuesto/solicitar', data={
        'descripcion': "O'ring de 1/2' y bomba hidráulica",
        'cantidad': 1,
        'observaciones': 'Para circuito de levante 12V'
    }, follow_redirects=True)
    assert res_rep1.status_code == 200

    # Verificar escape seguro de comillas simples en templates Jinja2
    res_admin_taller_check = client.get('/admin/taller')
    html_at = res_admin_taller_check.data.decode('utf-8')
    assert "abrirModalTramitar" in html_at
    assert ("O\\'ring" in html_at or "O\\&#39;ring" in html_at), "Las comillas simples en la descripción del repuesto deben escaparse para JS"

    res_taller_check = client.get('/taller')
    html_tc = res_taller_check.data.decode('utf-8')
    assert "abrirModalRecibirRepuesto" in html_tc
    assert ("O\\'ring" in html_tc or "O\\&#39;ring" in html_tc), "Las comillas simples en el panel taller deben escaparse para JS"

    res_rep2 = client.post(f'/taller/ot/{ot_id}/repuesto/solicitar', data={
        'descripcion': 'Junta y kit de retenes de alta presión',
        'cantidad': 2,
        'observaciones': 'Medida estándar'
    }, follow_redirects=True)
    assert res_rep2.status_code == 200

    reps = db.get_repuestos_ot(ot_id)
    assert len(reps) == 2
    rep1_id = reps[0]['id']
    rep2_id = reps[1]['id']
    assert reps[0]['estado'] == 'SOLICITADO'
    assert reps[1]['estado'] == 'SOLICITADO'
    print(f"  ✓ Operario solicitó 2 repuestos (con escape de comillas simples verificado): '{reps[0]['descripcion']}'.")

    # d. Administrativo confirma que el repuesto 1 está EN TRÁMITE DE COMPRA
    res_tramite = client.post(f'/admin/repuesto/{rep1_id}/tramitar', data={
        'datos_compra': 'OC #5021 - Proveedor HidroSur',
        'observaciones': 'Pactado arribo para mañana a primera hora'
    }, follow_redirects=True)
    assert res_tramite.status_code == 200

    reps_check1 = db.get_repuestos_ot(ot_id)
    assert reps_check1[0]['estado'] == 'EN_TRAMITE'
    assert reps_check1[0]['datos_compra'] == 'OC #5021 - Proveedor HidroSur'
    assert reps_check1[1]['estado'] == 'SOLICITADO'
    print("  ✓ Administrativo confirmó trámite de compra para repuesto 1 (Repuesto 2 sigue solicitado).")

    # e. Operario de taller confirma la RECEPCIÓN FÍSICA del repuesto 1 en galpón
    res_recibir1 = client.post(f'/taller/repuesto/{rep1_id}/recibir', data={
        'remito': 'Remito 0002-0045123',
        'observaciones': 'Ingresado por transportista en mano'
    }, follow_redirects=True)
    assert res_recibir1.status_code == 200

    reps_check2 = db.get_repuestos_ot(ot_id)
    assert reps_check2[0]['estado'] == 'RECIBIDO'
    assert reps_check2[0]['remito_recepcion'] == 'Remito 0002-0045123'
    assert reps_check2[1]['estado'] == 'SOLICITADO'
    print("  ✓ Operario confirmó recepción física del repuesto 1 con remito en galpón.")

    # f. Operario de taller confirma recepción física del repuesto 2
    res_recibir2 = client.post(f'/taller/repuesto/{rep2_id}/recibir', data={
        'remito': 'Remito 0002-0045124',
        'observaciones': 'Retenes completos verificados'
    }, follow_redirects=True)
    assert res_recibir2.status_code == 200

    reps_check3 = db.get_repuestos_ot(ot_id)
    assert reps_check3[0]['estado'] == 'RECIBIDO'
    assert reps_check3[1]['estado'] == 'RECIBIDO'
    ot_check_reps = db.get_ot_by_id(ot_id)
    assert ot_check_reps['estado_ot'] == 'EN_REPARACION'
    assert ot_check_reps['marca'] != '', "get_ot_by_id debe incluir marca del vehículo"
    assert ot_check_reps['modelo'] != '', "get_ot_by_id debe incluir modelo del vehículo"
    assert ot_check_reps['dominio'] != '', "get_ot_by_id debe incluir dominio del vehículo"
    assert 'dias_en_taller' in ot_check_reps, "get_ot_by_id debe incluir dias_en_taller"
    print("  ✓ Operario confirmó recepción del repuesto 2; get_ot_by_id verificado con contrato enriquecido.")

    # g. Alta operativa (Cierre de OT)
    res_cerrar = client.post(f'/taller/ot/{ot_id}/cerrar', data={
        'trabajo_realizado': 'Montaje de bomba y sellos nuevos concluido con éxito',
        'km_egreso': '125410'
    }, follow_redirects=True)
    assert res_cerrar.status_code == 200

    v_activo = db.find_vehicle_by_id('AE-1')
    assert v_activo['ESTADO'] == 'ACTIVO'
    assert v_activo['DIAGNÓSTICO'] == ''
    print("  ✓ Alta operativa otorgada: Unidad AE-1 retornó a 'ACTIVO'.")

    # 8. Test PRESERVACIÓN DE HISTORIALES (/historial/*)
    print("\n8. Probando preservación de los 4 accesos de /historial:")

    res_hist_mant = client.get('/historial/mantenimiento/AE-1')
    assert res_hist_mant.status_code == 200
    html_mant = res_hist_mant.data.decode('utf-8')
    assert "HISTORIAL DE REPARACIONES" in html_mant
    assert ot_num in html_mant

    # Verificar supresión de duplicados HISTÓRICO para la OT cerrada
    hist_records = db.get_history_records('AE-1', 'mantenimiento')
    historicos = [r for r in hist_records if r.get('OT / TIPO') == 'HISTÓRICO' and ot_num in r.get('FALLA / DETALLE', '')]
    assert len(historicos) == 0, "No debe haber duplicados HISTÓRICO de la OT cerrada"
    print("  ✓ /historial/mantenimiento/AE-1 integra la OT con sus avances y repuestos sin duplicados.")

    res_hist_img = client.get('/historial/imagenes/AE-1')
    assert res_hist_img.status_code == 200
    html_img = res_hist_img.data.decode('utf-8')
    assert "LEGAJO FOTOGRÁFICO" in html_img
    assert "AE-1" in html_img
    print("  ✓ /historial/imagenes/AE-1 renderiza el legajo fotográfico oficial.")

    res_hist_ing = client.get('/historial/ingresos/AE-1')
    assert res_hist_ing.status_code == 200
    assert "CONTROL DE INGRESOS" in res_hist_ing.data.decode('utf-8')
    print("  ✓ /historial/ingresos/AE-1 responde HTTP 200.")

    res_hist_cron = client.get('/historial/cronograma/AE-1')
    assert res_hist_cron.status_code == 200
    assert "CRONOGRAMA PREVENTIVO" in res_hist_cron.data.decode('utf-8')
    print("  ✓ /historial/cronograma/AE-1 responde HTTP 200.")

    # 9. Test eliminación de circuitos obsoletos
    print("\n9. Probando desmantelamiento de rutas obsoletas de kiosco:")
    assert client.get('/puesto/actividad').status_code == 404
    assert client.get('/operacion/actividad/AE-1').status_code == 404
    assert client.get('/taller/mecanico').status_code == 404
    print("  ✓ Rutas obsoletas de kiosco eliminadas limpiamente.")

    # 10. Test exportar Excel y restricciones
    print("\n10. Probando exportación Excel y reglas de negocio:")
    res_excel = client.get('/admin/exportar/excel')
    assert res_excel.status_code == 200
    assert "spreadsheetml" in res_excel.content_type

    res_patente = client.post('/api/vehiculo/actualizar', json={'id': 'AE-1', 'campo': 'dominio', 'valor': 'BLOQUEO'})
    assert res_patente.get_json().get('success') is False
    print("  ✓ Excel y bloqueo de edición de patente preservados sin regresión.")

    # Limpieza final de datos de prueba en la base de datos
    session_cleanup = db.get_session()
    session_cleanup.query(AvanceOT).filter(AvanceOT.orden_trabajo_id == ot_id).delete()
    session_cleanup.query(RepuestoOT).filter(RepuestoOT.orden_trabajo_id == ot_id).delete()
    session_cleanup.query(OrdenTrabajo).filter(OrdenTrabajo.id == ot_id).delete()
    session_cleanup.query(RegistroMantenimiento).filter(RegistroMantenimiento.vehiculo_id == 'AE-1').delete()
    session_cleanup.commit()
    session_cleanup.close()

    print("\n=== TODAS LAS PRUEBAS COMPLETADAS CON ÉXITO (100% OK) ===")

if __name__ == '__main__':
    run_tests()
