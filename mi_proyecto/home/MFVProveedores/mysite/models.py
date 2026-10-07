import json
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, DateTime, JSON, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class Vehiculo(Base):
    __tablename__ = 'vehiculos'

    id = Column(String(50), primary_key=True)  # Unidad (ej: AE-1, CH-6)
    tipo = Column(String(100), default='', index=True)
    marca = Column(String(100), default='')
    modelo = Column(String(150), default='')
    dominio = Column(String(50), default='', index=True)
    anio = Column(String(20), default='')
    area = Column(String(150), default='', index=True)
    estado = Column(String(100), default='ACTIVO', index=True)
    diagnostico = Column(Text, default='')
    resumen = Column(String(255), default='')
    patrimonio = Column(String(50), default='')
    motor = Column(String(100), default='')
    chasis = Column(String(100), default='')
    chofer = Column(String(150), default='')
    legajo = Column(String(50), default='')
    dni = Column(String(50), default='')
    foto_url = Column(String(500), default='')
    nfc_key = Column(String(100), default='', index=True)
    fecha_alta = Column(String(50), default='')
    
    # Campo NoSQL (Documento JSON embebido para especificaciones técnicas variables por tipo)
    especificaciones = Column(JSON, default=dict)

    creado_en = Column(DateTime, default=datetime.utcnow)
    actualizado_en = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        d = {
            'ID': self.id,
            'UNIDAD': self.id,
            'TIPO': self.tipo or '',
            'MARCA': self.marca or '',
            'MODELO': self.modelo or '',
            'DOMINIO': self.dominio or '',
            'AÑO': self.anio or '',
            'AREA': self.area or '',
            'ÁREA': self.area or '',
            'ESTADO': self.estado or 'ACTIVO',
            'DIAGNÓSTICO': self.diagnostico or '',
            'RESUMEN': self.resumen or '',
            'PATRIMONIO': self.patrimonio or '',
            'MOTOR': self.motor or '',
            'CHASIS': self.chasis or '',
            'CHOFER': self.chofer or '',
            'LEGAJO': self.legajo or '',
            'DNI': self.dni or '',
            'FOTO_URL': self.foto_url or '',
            'NFC_KEY': self.nfc_key or '',
            'FECHA_ALTA': self.fecha_alta or '',
            'ESPECIFICACIONES': self.especificaciones or {}
        }
        # Incluir especificaciones desglosadas para compatibilidad con vistas existentes
        if isinstance(self.especificaciones, dict):
            for k, v in self.especificaciones.items():
                if k not in d:
                    d[k] = v
        return d

class UnidadContratada(Base):
    __tablename__ = 'unidades_contratadas'

    id = Column(Integer, primary_key=True, autoincrement=True)
    tipo_c = Column(String(100), default='')
    area_c = Column(String(150), default='')
    cantidad_c = Column(Integer, default=1)
    solo_emergencia = Column(Boolean, default=False)
    de_prestamo = Column(String(150), default='')
    cantidad_p = Column(Integer, default=0)

    def to_dict(self):
        return {
            'TIPO_C': self.tipo_c or '',
            'AREA_C': self.area_c or '',
            'CANTIDAD_C': self.cantidad_c,
            'SOLO_EMERGENCIA': 'SI' if self.solo_emergencia else 'NO',
            'DE_PRESTAMO': self.de_prestamo or '',
            'CANTIDAD_P': self.cantidad_p
        }

class RegistroActividad(Base):
    __tablename__ = 'historial_actividad'

    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha = Column(String(50), nullable=False)
    vehiculo_id = Column(String(50), ForeignKey('vehiculos.id'), nullable=False, index=True)
    accion = Column(String(50), nullable=False)  # ENTRADA, SALIDA, NOVEDAD
    motivo = Column(Text, default='')
    responsable = Column(String(100), default='Supervisor Puerta')

    def to_dict(self):
        return {
            'FECHA': self.fecha,
            'ID': self.vehiculo_id,
            'ACCION': self.accion,
            'MOTIVO': self.motivo or '',
            'RESPONSABLE': self.responsable or ''
        }

class RegistroCombustible(Base):
    __tablename__ = 'historial_combustible'

    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha = Column(String(50), nullable=False)
    vehiculo_id = Column(String(50), ForeignKey('vehiculos.id'), nullable=False, index=True)
    tipo = Column(String(50), default='DIESEL')
    litros = Column(Float, default=0.0)
    km = Column(Float, default=0.0)

    def to_dict(self):
        return {
            'FECHA': self.fecha,
            'ID': self.vehiculo_id,
            'TIPO': self.tipo,
            'LITROS': str(self.litros),
            'KM': str(self.km)
        }

class RegistroFluidos(Base):
    __tablename__ = 'historial_fluidos'

    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha = Column(String(50), nullable=False)
    vehiculo_id = Column(String(50), ForeignKey('vehiculos.id'), nullable=False, index=True)
    categoria = Column(String(100), default='')
    subtipo = Column(String(100), default='')
    cantidad = Column(Float, default=0.0)

    def to_dict(self):
        return {
            'FECHA': self.fecha,
            'ID': self.vehiculo_id,
            'CAT': self.categoria,
            'SUBTIPO': self.subtipo,
            'CANT': str(self.cantidad)
        }

class RegistroMantenimiento(Base):
    __tablename__ = 'historial_mantenimiento'

    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha = Column(String(50), nullable=False)
    vehiculo_id = Column(String(50), ForeignKey('vehiculos.id'), nullable=False, index=True)
    tipo = Column(String(50), default='INTERNA')  # INTERNA, EXTERNA, LOGISTICA
    detalle = Column(Text, default='')

    def to_dict(self):
        return {
            'FECHA': self.fecha,
            'ID': self.vehiculo_id,
            'TIPO': self.tipo,
            'DETALLE': self.detalle or ''
        }

class RegistroPreventivo(Base):
    __tablename__ = 'historial_preventivos'

    id = Column(Integer, primary_key=True, autoincrement=True)
    fecha = Column(String(50), nullable=False)
    vehiculo_id = Column(String(50), ForeignKey('vehiculos.id'), nullable=False, index=True)
    tipo = Column(String(100), default='')
    responsable = Column(String(100), default='Auditor')
    detalle = Column(Text, default='')

    def to_dict(self):
        return {
            'FECHA': self.fecha,
            'ID': self.vehiculo_id,
            'TIPO': self.tipo,
            'RESPONSABLE': self.responsable,
            'DETALLE': self.detalle or ''
        }

class SolicitudRepuesto(Base):
    __tablename__ = 'solicitudes_repuestos'

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehiculo_id = Column(String(50), ForeignKey('vehiculos.id'), nullable=False, index=True)
    estado = Column(String(50), default='PENDIENTE')  # PENDIENTE, PEDIDO, DISPONIBLE
    nota = Column(Text, default='')
    fecha_update = Column(String(50), default='')
    tipo_registro = Column(String(50), default='REPUESTO')  # REPUESTO o INACTIVIDAD

    def to_dict(self):
        return {
            'ID': self.vehiculo_id,
            'ESTADO': self.estado,
            'NOTA': self.nota or '',
            'FECHA_UPDATE': self.fecha_update or '',
            'TIPO_REGISTRO': self.tipo_registro or 'REPUESTO'
        }

class CronogramaPreventivo(Base):
    __tablename__ = 'cronogramas_preventivos'

    id = Column(Integer, primary_key=True, autoincrement=True)
    vehiculo_id = Column(String(50), ForeignKey('vehiculos.id'), nullable=False, index=True)
    fecha_programada = Column(String(50), default='')
    tipo_mantenimiento = Column(String(100), default='')
    estado = Column(String(50), default='PENDIENTE')

    def to_dict(self):
        return {
            'ID': self.vehiculo_id,
            'FECHA_PROGRAMADA': self.fecha_programada,
            'TIPO_MANTENIMIENTO': self.tipo_mantenimiento,
            'ESTADO': self.estado
        }

class MetadataSync(Base):
    __tablename__ = 'metadata_sync'

    id = Column(Integer, primary_key=True, default=1)
    ultima_sincronizacion = Column(String(50), default='')
    filas_aux2 = Column(Integer, default=0)
    filas_aux3 = Column(Integer, default=0)
    estado_sync = Column(String(100), default='PENDIENTE')
    mensaje = Column(Text, default='')

class OrdenTrabajo(Base):
    __tablename__ = 'ordenes_trabajo'

    id = Column(Integer, primary_key=True, autoincrement=True)
    numero_ot = Column(String(50), unique=True, index=True)
    vehiculo_id = Column(String(50), ForeignKey('vehiculos.id'), nullable=False, index=True)
    
    fecha_ingreso = Column(String(50), nullable=False)
    fecha_egreso = Column(String(50), default='')
    
    estado_ot = Column(String(50), default='EN_REPARACION', index=True)
    prioridad = Column(String(20), default='NORMAL')
    sistema_afectado = Column(String(100), default='MECANICA')
    
    mecanico_asignado = Column(String(150), default='')
    motivo_ingreso = Column(Text, default='')
    trabajo_realizado = Column(Text, default='')
    repuestos_detalle = Column(Text, default='')
    km_ingreso = Column(String(50), default='')
    km_egreso = Column(String(50), default='')
    inmoviliza_unidad = Column(Boolean, default=True)

    def to_dict(self):
        return {
            'id': self.id,
            'numero_ot': self.numero_ot or '',
            'vehiculo_id': self.vehiculo_id,
            'fecha_ingreso': self.fecha_ingreso or '',
            'fecha_egreso': self.fecha_egreso or '',
            'estado_ot': self.estado_ot or 'EN_REPARACION',
            'prioridad': self.prioridad or 'NORMAL',
            'sistema_afectado': self.sistema_afectado or 'MECANICA',
            'mecanico_asignado': self.mecanico_asignado or '',
            'motivo_ingreso': self.motivo_ingreso or '',
            'trabajo_realizado': self.trabajo_realizado or '',
            'repuestos_detalle': self.repuestos_detalle or '',
            'km_ingreso': self.km_ingreso or '',
            'km_egreso': self.km_egreso or '',
            'inmoviliza_unidad': bool(self.inmoviliza_unidad)
        }


