FROM python:3.11-slim

# Evitar escritura de bytecode y habilitar buffer de salida directo
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000

WORKDIR /app

# Instalar dependencias primero (aprovechando caché de capas de Docker)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código del proyecto al contenedor
COPY mi_proyecto/home/MFVProveedores/mysite/ .

# Exponer el puerto
EXPOSE 5000

# Ejecutar con Gunicorn para entorno robusto
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "120", "flask_app:app"]
