from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Response, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from graphs.incidente_graph import get_app, grafo_listo, iniciar_grafo
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage
from loguru import logger
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from service.embedding_service import get_embedding, get_embeddings_lote, chunk_text
from service.observability import (
    INCIDENTES_TOTAL,
    INCIDENTE_DURACION,
    configurar_logging,
    get_request_id,
    set_request_context,
)
from service.auth import (
    COOKIE_CONVERSACION,
    Tenant,
    conversacion_de_cookie,
    establecer_cookie,
    resolver_conversacion,
    tenant_actual,
    tenant_admin,
    thread_id_de,
)
from service.errors import (
    ErrorDeDominio,
    PresupuestoDeTiempoAgotado,
    clasificar,
)
from database.db import cerrar_pool, get_pool
from database.vector_db import store_document_chunk, store_incident_embedding
from pypdf import PdfReader
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
import asyncio
import hashlib
import io
import os
import uuid
import time

configurar_logging()

# Tope de subida para la ingesta de PDF. Antes no había ninguno: un archivo enorme
# se leía entero en memoria y disparaba una llamada de embeddings por fragmento.
MAX_PDF_BYTES = int(os.getenv("MAX_PDF_MB", "20")) * 1024 * 1024

# Estado de los trabajos de ingesta en memoria. Alcanza mientras haya un worker;
# con varias réplicas hay que moverlo a Postgres o Redis para que el cliente pueda
# consultar un job desde cualquiera de ellas.
TRABAJOS_INGESTA: dict[str, dict] = {}

# Presupuesto total del grafo. Los timeouts por llamada (30 s en models/llm.py) no
# acotan el total: un workflow hace 5-6 llamadas al LLM más 3 de embeddings, así que
# el peor caso teórico pasa de cuatro minutos y el cliente no tiene forma de saber que
# ya no va a llegar nada. Un incidente real tarda 10-15 s; 120 es cuatro veces eso.
GRAFO_PRESUPUESTO_S = float(os.getenv("GRAFO_PRESUPUESTO_SEGUNDOS", "120"))

# Orígenes permitidos para CORS. Vacío por defecto: el navegador entonces no deja que
# ninguna página de otro origen llame a la API, que es lo correcto mientras no se sepa
# desde dónde se la va a consumir. `*` nunca, porque con credenciales no es válido.
CORS_ORIGENES = [o.strip() for o in os.getenv("CORS_ORIGENES", "").split(",") if o.strip()]

# Límite por tenant. Con la cuota del proveedor como techo real (~3,7 req/s en total),
# un solo cliente agresivo consume la capacidad de todos: esto reparte.
LIMITE_INCIDENTES = os.getenv("RATE_LIMIT_INCIDENTES", "30/minute")
LIMITE_INGESTA = os.getenv("RATE_LIMIT_INGESTA", "5/minute")

# Límite general para las rutas que no declaran uno propio. Lo aplica un middleware,
# así que corre antes del enrutado y no cuesta una consulta a la base por petición.
LIMITE_GENERAL = os.getenv("RATE_LIMIT_GENERAL", "120/minute")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Abre el pool y compila el grafo al arrancar, y los cierra al apagar.

    Esto es lo que permite que el proceso arranque aunque Postgres todavía no esté:
    si falla, se registra y el servicio queda vivo respondiendo 503 en `/ready` hasta
    que la base vuelva, en vez de morir al importar el módulo.
    """
    try:
        await get_pool()
        await iniciar_grafo()
        logger.info("[ARRANQUE] Pool y grafo listos")
    except Exception as e:
        logger.error(f"[ARRANQUE] No se pudo inicializar: {e}. El servicio arranca degradado.")
    yield
    await cerrar_pool()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGENES,
    allow_credentials=True,   # la cookie de conversación tiene que viajar
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
)


# ─── Rate limiting ────────────────────────────────────────────────────────────

def _clave_de_limite(request: Request) -> str:
    """
    Agrupa el límite por tenant, no por IP.

    Se usa el hash de la API key en vez de resolver el tenant contra la base: la clave
    identifica al tenant igual de bien y esta función corre en cada petición, así que
    una consulta SQL acá sería una por request solo para contar. Sin credencial se cae
    a la IP, que cubre el tráfico que aún no se autenticó.
    """
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"tenant:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
    return f"ip:{get_remote_address(request)}"


# El contador vive en memoria: con varias réplicas el límite efectivo se multiplica
# por el número de réplicas. Para un límite global hay que darle a slowapi un storage
# compartido (`storage_uri` con Redis) o moverlo al gateway.
limiter = Limiter(key_func=_clave_de_limite, default_limits=[LIMITE_GENERAL])
app.state.limiter = limiter

# El middleware aplica LIMITE_GENERAL a las rutas sin decorador. Las que sí lo tienen
# quedan exentas automáticamente (slowapi deja que el decorador decida), así que las
# dos capas no se pisan.
#
# Diferencia que importa al interpretar un 429: el middleware corre **antes** del
# enrutado, mientras que el decorador corre después de resolver las dependencias, o
# sea después de autenticar. Así que el límite por tenant no frena una avalancha de
# credenciales inválidas —cada una paga un SELECT por índice antes de ser rechazada—.
# Frenar eso es trabajo del gateway o del WAF, que es donde el plan lo ubica.
app.add_middleware(SlowAPIMiddleware)


# ─── Manejo de errores ────────────────────────────────────────────────────────

def _responder_error(exc: Exception) -> JSONResponse:
    """
    Traduce una excepción a la respuesta que ve el cliente.

    Dos cosas que antes no pasaban. Primero, el cliente recibe un `codigo` estable y
    un mensaje escrito para leerse, nunca `str(e)`: ese `detail` devolvía mensajes de
    psycopg con nombres de tabla y rutas del filesystem. Segundo, un 429 del proveedor
    sale como 503 con `Retry-After` en vez de 500, que es la diferencia entre decirle
    al cliente "tu petición está mal" y "vuelve en 10 segundos".

    El `error_id` es el puente: es lo único técnico que viaja al cliente, y con él se
    encuentra en el log la cadena de excepciones completa hasta la causa original.
    """
    dominio = clasificar(exc)
    error_id = uuid.uuid4().hex[:12]

    nivel = "warning" if dominio.http_status < 500 else "error"
    logger.opt(exception=exc).bind(error_id=error_id, codigo=dominio.codigo).log(
        nivel.upper(), f"[ERROR] {dominio.codigo} | error_id={error_id}"
    )

    cabeceras = {"Retry-After": str(dominio.retry_after)} if dominio.retry_after else None
    return JSONResponse(
        status_code=dominio.http_status,
        content={
            "error": {
                "codigo": dominio.codigo,
                "mensaje": dominio.mensaje_publico,
                "error_id": error_id,
            }
        },
        headers=cabeceras,
    )


@app.exception_handler(ErrorDeDominio)
async def manejar_error_de_dominio(_: Request, exc: ErrorDeDominio) -> JSONResponse:
    return _responder_error(exc)


@app.exception_handler(Exception)
async def manejar_error_inesperado(_: Request, exc: Exception) -> JSONResponse:
    """
    Red de seguridad para lo que no se envolvió.

    `clasificar` recorre la cadena de causas, así que un 429 de OpenAI o un pool
    agotado que lleguen por un camino no previsto siguen saliendo con el status
    correcto en vez de un 500 opaco.
    """
    return _responder_error(exc)


@app.exception_handler(RateLimitExceeded)
def manejar_limite_excedido(_: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    429 con `Retry-After`: el límite es nuestro, no del proveedor.

    Es `def` y no `async def` a propósito. `SlowAPIMiddleware` solo puede invocar
    handlers síncronos; con uno asíncrono se cae en silencio al handler por defecto de
    slowapi, que devuelve texto plano y no el sobre de error de la API. El resultado
    sería que el mismo 429 tiene dos formatos según qué capa lo detectó.
    """
    logger.warning(f"[LIMITE] Cuota de peticiones excedida | limite={exc.detail}")
    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "codigo": "limite_excedido",
                "mensaje": f"Superaste el límite de peticiones ({exc.detail}).",
            }
        },
        headers={"Retry-After": "60"},
    )


# ─── Correlación de logs ──────────────────────────────────────────────────────

@app.middleware("http")
async def correlacionar_request(request: Request, call_next):
    """
    Asigna un request_id a cada petición y lo deja en el contexto para que todas
    las líneas de log del workflow lo lleven. Si el cliente manda `X-Request-ID`
    se respeta, para poder seguir una traza que empieza en otro servicio.
    """
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    # La conversación ya no se identifica con el valor crudo de la cookie, así que acá
    # solo se fija el request_id; el identificador de conversación lo pone cada
    # endpoint cuando ya autenticó al tenant y verificó la firma.
    set_request_context(request_id, "-")
    respuesta = await call_next(request)
    respuesta.headers["X-Request-ID"] = request_id
    return respuesta


# ─── Health y readiness ───────────────────────────────────────────────────────

@app.get("/health")
@limiter.exempt
def health():
    """
    Liveness: ¿el proceso está vivo? No toca ninguna dependencia a propósito —
    si fallara cuando Postgres se cae, el orquestador reiniciaría el pod por un
    problema que no está en el pod.

    Exenta del rate limiting, y no es un detalle: bajo carga el orquestador sigue
    sondeando, así que un 429 acá se leería como "el pod no responde" y reiniciaría
    instancias sanas justo en el pico. Es además la única métrica que mide la
    aplicación y no la cuota del proveedor (ver docs/baseline-carga.md).
    """
    return {"status": "ok"}


@app.get("/ready")
@limiter.exempt
async def ready(response: Response):
    """
    Readiness: ¿puede atender tráfico? Verifica lo que un request necesita de verdad,
    que es Postgres (checkpointer + RAG) y el grafo compilado. Devuelve 503 si no,
    para que el balanceador deje de enrutar en vez de acumular errores.

    Si el arranque falló porque la base no estaba, reintenta inicializar: así el
    servicio se recupera solo cuando Postgres vuelve, sin reiniciar el contenedor.
    """
    checks = {"grafo": grafo_listo(), "postgres": False}
    try:
        pool = await get_pool()
        async with pool.connection() as conexion:
            await conexion.execute("SELECT 1")
        checks["postgres"] = True
        if not checks["grafo"]:
            await iniciar_grafo()
            checks["grafo"] = grafo_listo()
    except Exception as e:
        logger.warning(f"[READY] Postgres no disponible: {e}")

    listo = all(checks.values())
    if not listo:
        response.status_code = 503
    return {"status": "ready" if listo else "not_ready", "checks": checks}


@app.get("/metrics")
@limiter.exempt
def metrics():
    """Métricas en formato Prometheus: latencia por nodo, incidentes, tokens y errores."""
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ─── Modelos de request / response ───────────────────────────────────────────

class IncidentRequest(BaseModel):
    user_input: str


class HistoricalIncidentRequest(BaseModel):
    description: str
    category: str
    priority: str
    resolution: str


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_config(thread_id: str) -> dict:
    """
    Config del checkpointer para un hilo.

    El `thread_id` lo deriva `service/auth.py` de la identidad autenticada más el
    identificador de conversación: nunca es un valor que el cliente mande. Eso es lo
    que cierra el IDOR, y por eso esta función ya no recibe el `session_id` crudo.
    """
    return {
        "configurable": {"thread_id": thread_id},
        "metadata": {"thread_id": thread_id},
        "run_name": "incident_workflow",
    }


# ─── Endpoint de incidentes ───────────────────────────────────────────────────

@app.post("/incident")
@limiter.limit(LIMITE_INCIDENTES)
async def handle_incident(
    request: Request,
    payload: IncidentRequest,
    response: Response,
    tenant: Tenant = Depends(tenant_actual),
):
    """
    Procesa un incidente reportado por el usuario.

    El parámetro se llama `request` porque `slowapi` lo busca por ese nombre exacto
    para aplicar el límite; el cuerpo pasó a llamarse `payload`.
    """
    conversacion_id, thread_id = resolver_conversacion(request, response, tenant)
    # El contexto se refresca acá y no en el middleware: hasta este punto no se sabe
    # qué conversación es, porque hace falta el tenant para derivar el hilo.
    set_request_context(get_request_id(), conversacion_id)
    config = _get_config(thread_id)

    incident_app = get_app()
    estado_actual = await incident_app.aget_state(config)
    es_nueva_conversacion = not estado_actual.values

    if es_nueva_conversacion:
        # Primera vez: estado completo desde cero
        input_state = {
            "messages": [HumanMessage(content=payload.user_input)],
            "category": None,
            "priority": None,
            "possible_causes": None,
            "recommendations": None,
            "current_step": None,
        }
    else:
        # Conversación existente: solo añade el nuevo mensaje al historial acumulado.
        # LangGraph aplica el reducer add_messages, que AGREGA (no reemplaza) el
        # nuevo HumanMessage a los mensajes ya guardados en el checkpoint.
        # Se reinicia current_step para que el orquestador vuelva a clasificar.
        input_state = {
            "messages": [HumanMessage(content=payload.user_input)],
            "current_step": None,
        }

    tipo = "nueva" if es_nueva_conversacion else "continuacion"
    logger.info(
        f"[REQUEST] Incidente recibido | tenant={tenant.nombre} | "
        f"conversacion={conversacion_id[:8]}... | tipo={tipo} | input='{payload.user_input[:60]}'"
    )

    inicio = time.perf_counter()
    try:
        # Presupuesto total del workflow. Sin esto los timeouts por llamada no acotan
        # el conjunto: el cliente se queda esperando minutos por algo que ya no va a
        # llegar, y la corrutina sigue consumiendo cuota del proveedor mientras tanto.
        result = await asyncio.wait_for(
            incident_app.ainvoke(input_state, config=config),
            timeout=GRAFO_PRESUPUESTO_S,
        )
    except asyncio.TimeoutError as e:
        INCIDENTES_TOTAL.labels(resultado="error").inc()
        INCIDENTE_DURACION.observe(time.perf_counter() - inicio)
        raise PresupuestoDeTiempoAgotado(
            f"El workflow superó el presupuesto de {GRAFO_PRESUPUESTO_S:.0f}s."
        ) from e
    except Exception:
        INCIDENTES_TOTAL.labels(resultado="error").inc()
        INCIDENTE_DURACION.observe(time.perf_counter() - inicio)
        # Se relanza tal cual: el handler global clasifica la causa y arma la
        # respuesta. Antes acá se hacía HTTPException(500, detail=str(e)), que
        # devolvía al cliente el texto crudo de la excepción.
        raise

    duracion = time.perf_counter() - inicio
    INCIDENTE_DURACION.observe(duracion)
    INCIDENTES_TOTAL.labels(resultado="ok" if result else "error").inc()

    if not result:
        return {"error": "No se pudo procesar el incidente"}

    logger.info(
        f"[REQUEST] Completado | conversacion={conversacion_id[:8]}... | "
        f"categoria={result.get('category')} | prioridad={result.get('priority')} | "
        f"tiempo_total={duracion:.2f}s"
    )

    return {
        "conversacion_id": conversacion_id,
        "nueva_conversacion": es_nueva_conversacion,
        "category": result.get("category"),
        "priority": result.get("priority"),
        "possible_causes": result.get("possible_causes"),
        "recommendations": result.get("recommendations"),
        "current_step": result.get("current_step"),
    }


# ─── Endpoint de historial de conversación ────────────────────────────────────

@app.get("/conversation")
async def get_conversation(request: Request, tenant: Tenant = Depends(tenant_actual)):
    """
    Retorna el historial de mensajes de la conversación actual.

    Este endpoint era el IDOR: leía el `session_id` de la cookie y lo usaba tal cual
    como `thread_id`, así que escribirla a mano con el UUID de otra persona devolvía
    su historial completo de incidentes. Ahora el hilo se deriva del tenant
    autenticado, de modo que la misma cookie en otras manos apunta a otro hilo.

    No crea conversación si no hay cookie válida: un GET no debe tener efectos.
    """
    cookie = request.cookies.get(COOKIE_CONVERSACION)
    conversacion_id = conversacion_de_cookie(cookie)
    if conversacion_id is None:
        return {"conversacion_id": None, "messages": []}

    set_request_context(get_request_id(), conversacion_id)
    config = _get_config(thread_id_de(tenant, conversacion_id))
    state = await get_app().aget_state(config)

    if not state.values:
        return {"conversacion_id": conversacion_id, "messages": []}

    historial = []
    for msg in state.values.get("messages", []):
        if isinstance(msg, HumanMessage) and msg.content:
            historial.append({"role": "usuario", "content": msg.content})
        elif isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            historial.append({"role": "agente", "content": msg.content})

    return {"conversacion_id": conversacion_id, "messages": historial}


# ─── Endpoint para reiniciar conversación ─────────────────────────────────────

@app.delete("/conversation")
async def reset_conversation(response: Response, tenant: Tenant = Depends(tenant_actual)):
    """
    Reinicia la conversación emitiendo un identificador nuevo.

    El historial anterior queda en la base pero deja de ser alcanzable: su `thread_id`
    dependía del identificador que acaba de reemplazarse.
    """
    nuevo = str(uuid.uuid4())
    establecer_cookie(response, nuevo)
    logger.info(f"[REQUEST] Conversación reiniciada | tenant={tenant.nombre}")
    return {
        "status": "success",
        "mensaje": "Conversación reiniciada correctamente.",
        "conversacion_id": nuevo,
    }


# ─── Endpoint de ingesta de PDF ───────────────────────────────────────────────

@app.post("/documents/ingest/pdf")
@limiter.limit(LIMITE_INGESTA)
async def ingest_pdf(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(..., description="Archivo PDF a ingestar"),
    source: str = Form(None, description="Nombre o identificador del documento (opcional)"),
    tenant: Tenant = Depends(tenant_admin),
):
    """
    Ingesta un archivo PDF en la base de conocimiento RAG. **Solo administradores.**

    El rol no es burocracia: este endpoint era público, y lo que escribe acaba en la
    base que el agente de recomendación consulta para responderle a todos los
    usuarios. Cualquiera podía inyectar contenido arbitrario en el RAG, que en la
    práctica es prompt injection persistente contra todo el sistema.

    El PDF se lee página por página, el texto extraído se divide en fragmentos
    solapados, cada fragmento se vectoriza con OpenAI text-embedding-3-small
    y se almacena en knowledge_base para que el agente de recomendación
    pueda recuperarlo durante el flujo RAG.

    Form data:
        file   – archivo PDF
        source – identificador opcional (por defecto usa el nombre del archivo)

    Devuelve `202 Accepted` con un `job_id`; el progreso se consulta en
    `GET /documents/ingest/{job_id}`.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF.")

    contenido_bytes = await file.read()
    if len(contenido_bytes) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"El archivo supera el límite de {MAX_PDF_BYTES // (1024 * 1024)} MB.",
        )

    source_name = source or file.filename

    # El texto se extrae acá (es rápido y permite rechazar un PDF inválido con un
    # error inmediato); lo que se manda al background es la parte lenta, que son
    # los embeddings y las escrituras.
    try:
        reader = PdfReader(io.BytesIO(contenido_bytes))
        paginas = [p.extract_text().strip() for p in reader.pages if p.extract_text() and p.extract_text().strip()]
    except Exception as e:
        logger.error(f"No se pudo leer el PDF '{source_name}': {e}")
        raise HTTPException(status_code=400, detail="El archivo no es un PDF legible.")

    if not paginas:
        raise HTTPException(status_code=422, detail="No se pudo extraer texto del PDF.")

    chunks = chunk_text("\n\n".join(paginas))
    job_id = str(uuid.uuid4())
    TRABAJOS_INGESTA[job_id] = {
        "status": "en_proceso",
        "source": source_name,
        "pages_processed": len(reader.pages),
        "chunks_total": len(chunks),
        "chunks_stored": 0,
    }
    background.add_task(_procesar_ingesta, job_id, chunks, source_name)

    logger.info(
        f"[INGESTA] Aceptado '{source_name}' | tenant={tenant.nombre} | "
        f"job={job_id} | {len(chunks)} fragmentos"
    )
    return JSONResponse(
        status_code=202,
        content={"status": "accepted", "job_id": job_id, "chunks_total": len(chunks)},
    )


async def _procesar_ingesta(job_id: str, chunks: list[str], source_name: str) -> None:
    """
    Vectoriza y almacena los fragmentos fuera del ciclo del request.

    Los embeddings van en lote: antes era una llamada por fragmento, en serie, que
    para un manual de 100 páginas son cientos de viajes de ida y vuelta con el
    proceso entero bloqueado.
    """
    trabajo = TRABAJOS_INGESTA[job_id]
    try:
        embeddings = await get_embeddings_lote(chunks)
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            await store_document_chunk(
                content=chunk,
                embedding=embedding,
                source=source_name,
                chunk_index=i,
            )
            trabajo["chunks_stored"] = i + 1
        trabajo["status"] = "completado"
        logger.info(f"[INGESTA] '{source_name}' completado | job={job_id} | {len(chunks)} fragmentos")
    except Exception as e:
        trabajo["status"] = "error"
        trabajo["error"] = str(e)
        logger.error(f"[INGESTA] '{source_name}' fallo | job={job_id} | {e}")


@app.get("/documents/ingest/{job_id}")
def estado_ingesta(job_id: str, tenant: Tenant = Depends(tenant_admin)):
    """Progreso de un trabajo de ingesta. Solo administradores, igual que el alta."""
    trabajo = TRABAJOS_INGESTA.get(job_id)
    if trabajo is None:
        raise HTTPException(status_code=404, detail="No existe ese trabajo de ingesta.")
    return {"job_id": job_id, **trabajo}


# ─── Endpoint de incidentes históricos ───────────────────────────────────────

@app.post("/incidents/historical")
async def add_historical_incident(
    payload: HistoricalIncidentRequest,
    tenant: Tenant = Depends(tenant_admin),
):
    """
    Agrega un incidente resuelto a la base vectorial. **Solo administradores.**

    Mismo razonamiento que la ingesta de PDF: escribe en una de las tablas que
    alimentan el RAG del agente de recomendación.

    La descripción del incidente se vectoriza y se almacena en incident_embeddings
    para que el agente de recomendación pueda recuperar resoluciones similares vía RAG.

    Body:
        description – qué ocurrió
        category    – p.ej. "Error backend"
        priority    – p.ej. "Alta"
        resolution  – cómo se resolvió
    """
    embedding = await get_embedding(payload.description)
    incident_id = await store_incident_embedding(
        description=payload.description,
        category=payload.category,
        priority=payload.priority,
        resolution=payload.resolution,
        embedding=embedding,
    )
    logger.info(f"Incidente histórico almacenado | id={incident_id} | tenant={tenant.nombre}")
    return {"status": "success", "incident_id": incident_id}
