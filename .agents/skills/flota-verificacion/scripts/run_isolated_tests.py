import os
import sys
import json
import hashlib
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone

# Forzar UTF-8 en consola Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
MYSITE_DIR = os.path.join(REPO_ROOT, 'mi_proyecto', 'home', 'MFVProveedores', 'mysite')
PROD_DB_PATH = os.path.join(MYSITE_DIR, 'flota.db')


def compute_sha256(filepath):
    """Calcula el hash SHA-256 leyendo en modo compartido compatible con Windows."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    print("=================================================================")
    print("=== RUNNER DE VERIFICACIÓN AISLADA — PANEL FLOTA MUNICIPAL    ===")
    print("=================================================================")

    if not os.path.exists(PROD_DB_PATH):
        raise FileNotFoundError(f"No se encontró la base de datos en {PROD_DB_PATH}")

    hash_before = compute_sha256(PROD_DB_PATH)
    print(f"[PRE-CHECK] SHA-256 inicial de flota.db: {hash_before}")

    fd, temp_db_path = tempfile.mkstemp(prefix='flota_isolated_verify_', suffix='.db')
    os.close(fd)

    try:
        # Clonar flota.db usando la API de backup transaccional de SQLite
        src_conn = sqlite3.connect(PROD_DB_PATH)
        dst_conn = sqlite3.connect(temp_db_path)
        src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()

        os.environ['FLOTA_DB_PATH'] = temp_db_path
        if MYSITE_DIR not in sys.path:
            sys.path.insert(0, MYSITE_DIR)

        import db_service as db
        from flask_app import app
        from models import MetadataSync, AvanceOT, RepuestoOT, OrdenTrabajo
        import test_integration

        assert os.path.abspath(db.DB_PATH) == os.path.abspath(temp_db_path), (
            f"db_service apunta a {db.DB_PATH} en lugar del clon temporal {temp_db_path}"
        )
        print(f"[AISLAMIENTO] Ejecutando pruebas sobre clon temporal: {temp_db_path}")

        # 1. Ejecutar los 10 bloques de test_integration.py
        test_integration.run_tests()

        # 2. Ejecutar chequeos adversariales adicionales de contratos e integridad
        print("\n=== EJECUTANDO CHEQUEOS ADVERSARIALES DE CONTRATO E INTEGRIDAD ===")

        # Check A: Inmutabilidad en todas las variantes de mayúsculas/minúsculas
        for field in ['id', 'ID', 'Id', 'unidad', 'UNIDAD', 'dominio', 'DOMINIO', 'patente', 'PATENTE']:
            res = db.update_vehicle_cell('AE-1', field, 'VALOR_NO_PERMITIDO')
            assert res['success'] is False, f"El campo {field} no debió ser editable"
            assert 'no es editable' in res['error']
        print("  ✓ [Adversarial 1] Bloqueo de identificadores inmutables (case-insensitive) OK.")

        # Check B: Mapeo de columnas relacionales vs JSON especificaciones
        assert db.update_vehicle_cell('AE-1', 'marca', 'AUDIT_BRAND')['success'] is True
        assert db.update_vehicle_cell('AE-1', 'anio', '2025')['success'] is True
        con_tmp = sqlite3.connect(temp_db_path)
        cur_tmp = con_tmp.cursor()
        cur_tmp.execute("SELECT marca, anio, especificaciones FROM vehiculos WHERE id='AE-1'")
        row = cur_tmp.fetchone()
        assert row[0] == 'AUDIT_BRAND' and row[1] == '2025'
        specs = json.loads(row[2]) if row[2] else {}
        assert 'marca' not in specs and 'anio' not in specs
        con_tmp.close()
        print("  ✓ [Adversarial 2] Mapeo de columnas SQL vs JSON especificaciones OK.")

        # Check C: Huso horario Argentina UTC-3 en fallback de update_status_repuesto
        db.update_status_repuesto('AE-1', 'SOLICITADO', 'Check horario UTC-3')
        rep_status = db.get_status_repuesto('AE-1')
        assert rep_status is not None
        dt = datetime.strptime(rep_status['FECHA_UPDATE'], '%d/%m/%Y %H:%M:%S')
        expected_arg = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=3)
        assert abs((dt - expected_arg).total_seconds()) < 60
        db.update_status_repuesto('AE-1', None)
        print("  ✓ [Adversarial 3] Sello temporal UTC-3 en update_status_repuesto OK.")

        # Check D: Integridad de la base de datos real flota.db
        con_prod = sqlite3.connect(PROD_DB_PATH)
        cur_prod = con_prod.cursor()
        assert cur_prod.execute("PRAGMA integrity_check").fetchall() == [('ok',)]
        assert cur_prod.execute("PRAGMA foreign_key_check").fetchall() == []
        vehiculos_count = cur_prod.execute("SELECT COUNT(*) FROM vehiculos").fetchone()[0]
        con_prod.close()
        print(f"  ✓ [Adversarial 4] Salud de flota.db verificada (integrity=ok, vehiculos={vehiculos_count}).")

        # Check E: Seguridad de rutas /admin/* y /api/* vs acceso directo a /taller y filtrado PUBLIC_CONF
        from flask_app import PUBLIC_CONF
        for secret_k in ('PASSWORD_ADMIN', 'PASSWORD_PANEL', 'SECRET_KEY'):
            assert secret_k not in PUBLIC_CONF, f"{secret_k} no debe exponerse en PUBLIC_CONF"
        anon_client = app.test_client()
        assert anon_client.get('/admin/planilla').status_code == 302
        assert anon_client.get('/admin/taller').status_code == 302
        assert anon_client.get('/admin/exportar/excel').status_code == 302
        assert anon_client.post('/api/vehiculo/actualizar', json={'id': 'AE-1', 'campo': 'marca', 'valor': 'X'}).status_code == 401
        assert anon_client.post('/api/sincronizar_sheets').status_code == 401
        assert anon_client.get('/taller').status_code == 200, "/taller debe permanecer de acceso directo"
        print("  ✓ [Adversarial 5] Guardas de sesión en /admin/* y /api/*, /taller directo y PUBLIC_CONF sin secretos OK.")

        # Check F: Bloqueo de regresión de estado en repuesto ya RECIBIDO
        ot_tmp = db.crear_orden_trabajo('AE-1', 'Prueba bloqueo repuesto recibido')
        rep_tmp = db.agregar_repuesto_ot(ot_tmp['id'], 'Filtro hidráulico')['repuesto']
        assert db.confirmar_recepcion_repuesto(rep_tmp['id'], 'REM-001')['success'] is True
        res_retro = db.confirmar_tramite_repuesto(rep_tmp['id'], 'OC-TARDIA')
        assert res_retro['success'] is False and 'ya fue recibido' in res_retro['error']
        s_tmp = db.get_session()
        s_tmp.query(AvanceOT).filter_by(orden_trabajo_id=ot_tmp['id']).delete()
        s_tmp.query(RepuestoOT).filter_by(orden_trabajo_id=ot_tmp['id']).delete()
        s_tmp.query(OrdenTrabajo).filter_by(id=ot_tmp['id']).delete()
        s_tmp.commit()
        s_tmp.close()
        db.update_vehicle_cell('AE-1', 'estado', 'ACTIVO')
        db.update_vehicle_cell('AE-1', 'diagnostico', '')
        print("  ✓ [Adversarial 6] Guarda de no-regresión en repuesto RECIBIDO OK.")

        # Check G: Retiro de /auditor + acoplamiento de Service Preventivo (directo y vía OT SERVICE) a /historial/cronograma/<id>
        assert anon_client.get('/auditor').status_code == 404, "/auditor debe responder 404"
        assert anon_client.get('/auditor/service/AE-1').status_code == 404, "/auditor/service/<id> debe responder 404"
        resp_prev = anon_client.post('/taller/preventivo/registrar', data={
            'vehiculo_id': 'AE-1',
            'tipo_service': 'SERVICE COMPLETO',
            'items_service': ['Aceite Motor', 'Filtro Aceite'],
            'responsable': 'M. Gómez',
            'kilometraje': '152000 km',
            'observaciones': 'Control preventivo desde galpón'
        }, follow_redirects=True)
        assert resp_prev.status_code == 200
        ot_srv = db.crear_orden_trabajo('AE-1', 'Service programado 10.000 km', sistema_afectado='SERVICE', mecanico_asignado='L. Sosa')
        assert db.cerrar_orden_trabajo(ot_srv['id'], trabajo_realizado='Cambio completo de filtros y fluidos', km_egreso='152500')['success'] is True
        crono_records = db.get_history_records('cronograma', 'AE-1')
        assert any('Control preventivo desde galpón' in r.get('DETALLE', '') for r in crono_records)
        assert any(ot_srv['numero_ot'] in r.get('DETALLE', '') for r in crono_records)
        resp_hist_crono = anon_client.get('/historial/cronograma/AE-1')
        assert resp_hist_crono.status_code == 200
        assert b'SERVICE COMPLETO' in resp_hist_crono.data
        print("  ✓ [Adversarial 7] Retiro de /auditor y acoplamiento de Service Preventivo a /historial/cronograma/<id> OK.")

        # Cerrar conexiones del clon temporal antes de borrarlo
        db.SessionLocal.remove()
        db.engine.dispose()

    finally:
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except Exception:
                pass

    hash_after = compute_sha256(PROD_DB_PATH)
    print(f"\n[POST-CHECK] SHA-256 final de flota.db:   {hash_after}")
    assert hash_before == hash_after, "¡ERROR CRÍTICO! flota.db fue modificada durante la ejecución de las pruebas."
    print("✓ [GARANTÍA DE AISLAMIENTO] flota.db permaneció 100% inmutable (SHA-256 idéntico).")
    print("=================================================================")
    print("=== VERIFICACIÓN AISLADA COMPLETADA CON ÉXITO (100% OK)       ===")
    print("=================================================================")


if __name__ == '__main__':
    main()

