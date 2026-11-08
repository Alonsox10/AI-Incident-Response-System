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

Crea un archivo `.env` en la raiz del proyecto con las variables obligatorias:

```env
OPENAI_API_KEY=sk-...
POSTGRES_URL=postgresql://postgres:alonso@localhost:5432/incident_ai
```

> En Docker el servicio usa internamente `postgresql://postgres:alonso@postgres:5432/incident_ai` (definido en `docker-compose.yml`). El `.env` es para correr la app localmente fuera de Docker.

Variables opcionales del camino de FAQs:

```env
# Similitud a partir de la cual una FAQ se devuelve tal cual, sin generarla con el LLM
FAQ_HIGH_CONFIDENCE_THRESHOLD=0.75

# Similitud con que el orquestador enruta directo a FAQ sin consultar al LLM
FAQ_ROUTING_THRESHOLD=0.85
```

- `FAQ_HIGH_CONFIDENCE_THRESHOLD` (default `0.75`) controla **como responde** el agente de FAQs. Subirlo lo hace mas conservador (sintetiza mas seguido con el LLM); bajarlo hace que devuelva respuestas almacenadas con mas frecuencia.
- `FAQ_ROUTING_THRESHOLD` (default `0.85`) controla **que llega** al agente de FAQs. Es deliberadamente mas alto: entre `0.75` y `0.85` caen los parafraseos de un sintoma activo ("mi equipo tarda mucho en prender hoy" da ~0.74), que deben pasar por el criterio del orquestador en vez de cortocircuitar a FAQ. Bajarlo acerca el sistema a "si existe una FAQ parecida, respondela"; subirlo, a "solo si la pregunta esta literalmente documentada".

### Observabilidad

El agente emite **logs JSON correlacionados** y expone **metricas Prometheus**. Un request completo produce ~25 lineas con el mismo `request_id`, de principio a fin:

```json
{"ts":"...","mensaje":"[ORQUESTADOR] Decision: classifier","request_id":"4e12c560-...","session_id":"9ca662e6-..."}
{"ts":"...","mensaje":"[NODO] orchestrator completado","nodo":"orchestrator","duracion_s":2.525,"request_id":"4e12c560-..."}
```

Si el cliente manda la cabecera `X-Request-ID`, se respeta, para poder seguir una traza que empieza en otro servicio.

| Variable | Default | Para que |
|---|---|---|
| `LOG_JSON` | `true` | `false` devuelve la salida legible de siempre, util en local |
| `LOG_LEVEL` | `INFO` | Nivel minimo |
| `LLM_COSTO_ENTRADA_POR_1M` | `0` | Tarifa por millon de tokens de entrada |
| `LLM_COSTO_SALIDA_POR_1M` | `0` | Tarifa por millon de tokens de salida |

Las dos tarifas valen 0 a proposito: los tokens se miden de verdad, pero el costo en USD solo se calcula si se configuran con las tarifas del contrato vigente. Una tarifa inventada produce un numero que parece medido y no lo es.

Metricas en `GET /metrics`: latencia por nodo (p50/p95), duracion de incidentes, tokens consumidos y errores por componente.

> **LangSmith esta desactivado.** Se usaba antes para las trazas, pero la clave devolvia `403` en cada paso del grafo y ensuciaba la salida. Las variables siguen comentadas en el `.env`. Lo que daba LangSmith lo cubren ahora los logs JSON y `/metrics`.

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

## 5. Aplicar el esquema y cargar los datos iniciales

Son dos pasos, en este orden. Ambos son seguros de repetir.

```bash
python scripts/migrate.py    # crea las tablas y los indices HNSW
python seed.py               # carga los datos
```

**Las migraciones ya no se aplican al arrancar la app.** Antes el DDL se ejecutaba al importar el grafo, asi que cada replica lo lanzaba en cada despliegue —incluido el `CREATE INDEX` HNSW, que sobre una tabla con datos es costoso y bloqueante—. Ahora `scripts/migrate.py` registra cada `.sql` aplicado en la tabla `schema_migrations` y no lo repite. Con `--estado` informa que falta sin tocar nada.

Que hace `seed.py` internamente:

1. Ingesta todos los PDFs de `docs/knowledge/` en `knowledge_base`
2. Carga 7 incidentes historicos resueltos en `incident_embeddings`
3. Parsea `docs/knowledge/faqs.md` y carga las preguntas frecuentes en `faqs`

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

El comando **no es el mismo en Linux que en Windows**:

```bash
# Linux / Mac / Docker
uvicorn main:app --reload
```

```bash
# Windows
uvicorn main:app --reload --loop asyncio:SelectorEventLoop
```

La API queda disponible en `http://127.0.0.1:8000`.

Documentacion interactiva (Swagger): `http://127.0.0.1:8000/docs`

### Por que Windows necesita el flag `--loop`

El acceso a PostgreSQL es asincrono, y **psycopg no puede trabajar en modo asincrono sobre el `ProactorEventLoop`**, que es el que Windows usa por defecto. Uvicorn lo impone en win32 pasandolo como `loop_factory`, lo que ademas ignora cualquier `set_event_loop_policy`. El flag `--loop` admite cualquier import string ademas de sus valores conocidos, asi que se le entrega la clase del loop correcto.

> **Si lo olvidas, el fallo es silencioso.** El servidor arranca sin ningun error visible, pero `/ready` devuelve `503` con `"postgres": false` indefinidamente y cualquier peticion a `/incident` falla. No veras un traceback que te oriente: si te pasa eso, lo primero que hay que mirar es el flag.

En Linux no hace falta porque alli uvicorn ya elige un `SelectorEventLoop`. Por eso el `Dockerfile` arranca sin el flag.

Si no quieres escribirlo cada vez, un alias lo resuelve sin tocar el repo:

```bash
alias api='uvicorn main:app --reload --loop asyncio:SelectorEventLoop'
```

### Comprobar que arranco bien

```bash
curl http://127.0.0.1:8000/health    # {"status":"ok"} siempre que el proceso este vivo
curl http://127.0.0.1:8000/ready     # debe dar {"grafo":true,"postgres":true}
```

`/ready` es el que importa: devuelve `503` mientras la base no responda o el grafo no haya compilado. El servicio esta pensado para arrancar aunque PostgreSQL todavia no este y recuperarse solo cuando aparezca, asi que un `503` al principio no es un error fatal.

---

## Endpoints principales

| Metodo | Endpoint | Descripcion |
|--------|----------|-------------|
| `POST` | `/incident` | Reportar un incidente (el agente responde con diagnostico y recomendaciones) |
| `GET` | `/conversation` | Ver el historial de mensajes de la sesion actual |
| `DELETE` | `/conversation` | Reiniciar la conversacion (nueva sesion) |
| `POST` | `/documents/ingest/pdf` | Ingestar un PDF en la base de conocimiento RAG. Responde **`202 Accepted`** con un `job_id`: el trabajo corre en segundo plano |
| `GET` | `/documents/ingest/{job_id}` | Progreso de una ingesta (`en_proceso` / `completado` / `error`) |
| `POST` | `/incidents/historical` | Agregar un incidente resuelto a la base vectorial |
| `GET` | `/health` | Liveness. Responde 200 mientras el proceso este vivo, sin tocar dependencias |
| `GET` | `/ready` | Readiness. **503** si PostgreSQL no responde o el grafo no compilo |
| `GET` | `/metrics` | Metricas en formato Prometheus |

La ingesta de PDF dejo de ser sincrona: antes bloqueaba el proceso entero mientras vectorizaba —un manual de 100 paginas congelaba el servicio varios minutos— y ahora devuelve el `job_id` de inmediato. El tamano maximo de subida se configura con `MAX_PDF_MB` (20 por defecto).

---

## Agregar nuevos documentos al RAG

Copia el PDF a la carpeta `docs/knowledge/` y ejecuta el seed de nuevo:

```bash
python seed.py
```

El script detecta los PDFs nuevos y solo ingesta los que aun no estan en la base de datos.

---

## Agregar nuevas FAQs

Las preguntas frecuentes viven en `docs/knowledge/faqs.md`, en Markdown plano. La convencion esta documentada al inicio de ese mismo archivo:

```markdown
## Categoria

### La pregunta tal como la formula el usuario

Severidad: Media

**Respuesta:**

Texto de la respuesta, hasta el siguiente encabezado.
```

Para agregar una FAQ, copia el bloque de cualquier caso existente, editalo y vuelve a correr:

```bash
python seed.py
```

> La ingesta de FAQs es idempotente a nivel de tabla: si `faqs` ya tiene datos, el paso se omite. Para recargarla tras editar el archivo, vacia la tabla primero (`TRUNCATE faqs;`) y vuelve a correr el seed.

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
4. python -m venv venv && activar el venv && pip install -r requirements.txt
5. python scripts/migrate.py
6. python seed.py
7. Arrancar:
     Linux/Mac -> uvicorn main:app --reload
     Windows   -> uvicorn main:app --reload --loop asyncio:SelectorEventLoop
8. Comprobar: curl http://127.0.0.1:8000/ready  ->  {"grafo":true,"postgres":true}
```

**Activar el venv no es opcional.** Si no esta activo, `python` resuelve al interprete del sistema y los comandos fallan con `ModuleNotFoundError: No module named 'prometheus_client'` (o `psycopg_pool`). Parece que falta instalar algo, pero lo que falla es el interprete. Alternativa sin activarlo: invocarlo directo con `./venv/Scripts/python.exe <comando>`.