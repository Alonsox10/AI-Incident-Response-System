FROM python:3.12-slim

WORKDIR /app

# Dependencias del sistema necesarias para psycopg y compilacion de paquetes
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias de Python (excluye win32_setctime, que es solo para Windows)
COPY requirements.txt .
RUN grep -v "win32" requirements.txt > /tmp/requirements-linux.txt && \
    pip install --no-cache-dir -r /tmp/requirements-linux.txt

# Copiar el codigo de la aplicacion
COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
