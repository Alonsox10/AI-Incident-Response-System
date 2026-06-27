# AI Incident Response System

Sistema multiagente de respuesta a incidentes TI con RAG (Retrieval-Augmented Generation) usando LangGraph, pgvector y FastAPI.

---

## Requisitos previos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) instalado y corriendo
- Python 3.11+
- Cuenta de OpenAI con API key

---

## 1. Clonar el repositorio

```bash
git clone <url-del-repositorio>
cd AI-Incident-Response-System
```

---

## 2. Configurar variables de entorno

Crea un archivo `.env` en la raiz del proyecto:

```env
OPENAI_API_KEY=sk-...
POSTGRES_URL=postgresql://postgres:alonso@localhost:5432/incident_ai
```

> En Docker el servicio usa internamente `postgresql://postgres:alonso@postgres:5432/incident_ai` (definido en `docker-compose.yml`). El `.env` es para correr la app localmente fuera de Docker.

---

## 3. Levantar el contenedor de PostgreSQL con pgvector

```bash
docker compose up -d
```

Esto levanta el servicio `postgres` con la imagen `pgvector/pgvector:pg16` y ejecuta automaticamente `init.sql` que crea la tabla `incidents` y activa la extension `vector`.

Verifica que el contenedor este saludable:

```bash
docker compose ps
```

Deberia ver `STATUS: healthy` en el servicio `postgres`.

Para ver los logs si hay algun problema:

```bash
docker compose logs postgres
```

---

## 4. Crear el entorno virtual e instalar dependencias

```bash
python -m venv venv

# Windows
.\venv\Scripts\activate

# Mac / Linux
source venv/bin/activate

pip install -r requirements.txt
```

---

## 5. Cargar los datos iniciales con seed.py

Este paso inicializa la base de conocimiento RAG. Solo se necesita ejecutar **una vez** por entorno. Es seguro ejecutarlo varias veces: detecta si los datos ya existen y no duplica nada.

```bash
python seed.py
```

Que hace internamente:

1. Crea las tablas vectoriales (`knowledge_base`, `incident_embeddings`) con sus indices HNSW
2. Ingesta todos los PDFs de `docs/knowledge/` en `knowledge_base`
3. Carga 7 incidentes historicos resueltos en `incident_embeddings`

Salida esperada:

```
========================================
   Seed - Sistema de Respuesta a Incidentes
========================================

[1/3] Inicializando tablas vectoriales...
  [ok] Tablas listas.

[2/3] Ingestando PDFs de knowledge base...
  Procesando 'IT_Incidents_Solutions_RAG.pdf'...
  [ok] 'IT_Incidents_Solutions_RAG.pdf' -> 4 paginas, 10 fragmentos almacenados.

[3/3] Cargando incidentes historicos...
  Cargando 7 incidentes historicos...
  [ok] 7 incidentes historicos almacenados.

========================================
   Seed completado correctamente.
========================================
```

> Si ves `[omitido]` en alguna seccion, significa que esos datos ya estaban cargados.

---

## 6. Iniciar la aplicacion

```bash
uvicorn main:app --reload
```

La API queda disponible en `http://127.0.0.1:8000`.

Documentacion interactiva (Swagger): `http://127.0.0.1:8000/docs`

---

## Endpoints principales

| Metodo | Endpoint | Descripcion |
|--------|----------|-------------|
| `POST` | `/incident` | Reportar un incidente (el agente responde con diagnostico y recomendaciones) |
| `GET` | `/conversation` | Ver el historial de mensajes de la sesion actual |
| `DELETE` | `/conversation` | Reiniciar la conversacion (nueva sesion) |
| `POST` | `/documents/ingest/pdf` | Ingestar un PDF en la base de conocimiento RAG |
| `POST` | `/incidents/historical` | Agregar un incidente resuelto a la base vectorial |

---

## Agregar nuevos documentos al RAG

Copia el PDF a la carpeta `docs/knowledge/` y ejecuta el seed de nuevo:

```bash
python seed.py
```

El script detecta los PDFs nuevos y solo ingesta los que aun no estan en la base de datos.

---

## Detener los contenedores

```bash
docker compose down
```

Los datos de PostgreSQL se conservan en el volumen `postgres_data`. Para eliminar tambien los datos:

```bash
docker compose down -v
```

---

## Resumen del flujo para un nuevo integrante

```
1. git clone <repo>
2. Crear .env con OPENAI_API_KEY y POSTGRES_URL
3. docker compose up -d
4. python -m venv venv && pip install -r requirements.txt
5. python seed.py
6. uvicorn main:app --reload
```