# Imagen base: Python 3.12 slim (sin extras innecesarios)
FROM python:3.12-slim

# Evita que Python genere archivos .pyc y que bufferee stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instala dependencias del sistema necesarias para psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copia toda la carpeta requirements primero para aprovechar el cache de Docker:
# si el código cambia pero los requirements no, Docker no reinstala paquetes.
# Necesitamos todos los archivos porque local.txt hace -r base.txt
COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/local.txt

# Copia el resto del código
COPY . .

EXPOSE 8000
