# Imagen multi-stage: se compila en una etapa y se corre en otra limpia.
#
# El motivo no es el tamaño, es la superficie: `gcc` y `libpq-dev` son herramientas de
# compilación, y dejarlas en la imagen que corre en producción le regala a cualquiera
# que consiga ejecución remota un compilador para construir lo que quiera. La etapa
# final no las tiene.

# ─── Etapa 1: dependencias ────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Dependencias del sistema necesarias solo para compilar paquetes de Python.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Las dependencias se instalan en un venv propio para poder copiar el árbol completo
# a la etapa final de una sola vez.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
# `win32_setctime` es una dependencia de loguru solo para Windows y no instala en
# Linux. La tarea 7 de la Fase 3 separa runtime de desarrollo en un requirements.in
# compilado, y con eso este grep desaparece.
RUN grep -v "win32" requirements.txt > /tmp/requirements-linux.txt && \
    pip install --no-cache-dir -r /tmp/requirements-linux.txt

# ─── Etapa 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim

# Usuario sin privilegios. Por defecto los contenedores corren como root, de modo que
# una escapada del contenedor empieza con uid 0 en el host.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 agente

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY --chown=agente:agente . .

USER agente

EXPOSE 8000

# Apunta a /health, que a propósito no toca Postgres: si consultara la base, una caída
# de la base reiniciaría un contenedor sano. La readiness —la que sí mira las
# dependencias— es /ready, y la consulta el orquestador, no Docker.
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

# Un worker por núcleo. `--workers` no se fija en un número acá: `WEB_CONCURRENCY` es
# la variable que uvicorn ya lee, y así el mismo despliegue se ajusta al tamaño de la
# máquina sin reconstruir la imagen. Ojo: cada worker abre su propio pool, así que el
# total de conexiones a Postgres es POSTGRES_POOL_MAX × workers.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
