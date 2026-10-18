"""
Observabilidad: logs correlacionables y métricas.

Tres piezas, todas opt-in desde el borde (main.py y el armado del grafo), para no
tocar la lógica de los agentes:

1. `request_id` / `session_id` en `contextvars`, que loguru inyecta en cada línea.
   Es lo que permite reconstruir un request completo cuando hay varias réplicas
   escribiendo al mismo stdout.
2. Métricas Prometheus: latencia por nodo, duración y resultado de cada incidente,
   tokens consumidos y errores por componente.
3. `medir_nodo`, que envuelve un nodo del grafo para cronometrarlo sin que el nodo
   se entere. Se aplica en `graphs/incidente_graph.py` al registrar cada uno.
"""
import json
import os
import sys
import time
from contextvars import ContextVar
from functools import wraps

from loguru import logger
from prometheus_client import Counter, Histogram

# ─── Contexto por request ─────────────────────────────────────────────────────

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_session_id: ContextVar[str] = ContextVar("session_id", default="-")


def set_request_context(request_id: str = "-", session_id: str = "-") -> None:
    _request_id.set(request_id)
    _session_id.set(session_id)


def get_request_id() -> str:
    return _request_id.get()


# ─── Logging estructurado ─────────────────────────────────────────────────────

def _serializar(record) -> str:
    """Una línea JSON por evento, con el contexto del request ya resuelto."""
    payload = {
        "ts": record["time"].isoformat(),
        "nivel": record["level"].name,
        "mensaje": record["message"],
        "modulo": record["name"],
        "funcion": record["function"],
        "linea": record["line"],
        "request_id": _request_id.get(),
        "session_id": _session_id.get(),
    }
    if record["exception"] is not None:
        payload["excepcion"] = repr(record["exception"].value)
    payload.update(record["extra"])
    return json.dumps(payload, ensure_ascii=False)


def _sink(message) -> None:
    print(_serializar(message.record), file=sys.stdout, flush=True)


def configurar_logging() -> None:
    """
    Reemplaza el sink por defecto de loguru por uno JSON.

    Se llama desde el lifespan de FastAPI. Los scripts de evaluación y los tests no
    la llaman, así que conservan la salida legible de siempre: el JSON es para que lo
    parsee un agregador en producción, no para leerlo a ojo.
    """
    if os.getenv("LOG_JSON", "true").lower() not in ("true", "1", "yes"):
        return
    logger.remove()
    logger.add(_sink, level=os.getenv("LOG_LEVEL", "INFO"))


# ─── Métricas ─────────────────────────────────────────────────────────────────

NODO_DURACION = Histogram(
    "agente_nodo_duracion_segundos",
    "Tiempo de ejecución de cada nodo del grafo",
    ["nodo"],
    # El camino de FAQ resuelve en ~1-5 s y el de incidente en ~10; los buckets
    # se eligen para que p50 y p95 caigan en tramos distintos en ambos casos.
    buckets=(0.25, 0.5, 1, 2, 3, 5, 8, 12, 20, 30, 60),
)

INCIDENTE_DURACION = Histogram(
    "incidente_duracion_segundos",
    "Tiempo total de un request de incidente, de extremo a extremo",
    buckets=(0.5, 1, 2, 3, 5, 8, 12, 20, 30, 60),
)

INCIDENTES_TOTAL = Counter(
    "incidentes_total",
    "Requests de incidente procesados",
    ["resultado"],  # ok | error
)

ERRORES_TOTAL = Counter(
    "errores_total",
    "Errores por componente",
    ["componente"],
)

TOKENS_TOTAL = Counter(
    "llm_tokens_total",
    "Tokens consumidos por el LLM",
    ["tipo"],  # entrada | salida
)

COSTO_TOTAL = Counter(
    "llm_costo_usd_total",
    "Costo acumulado estimado en USD. Vale 0 si no se configuraron las tarifas.",
)

# Tarifas por millón de tokens. Se dejan en 0 a propósito: una tarifa inventada
# produce un número que parece medido y no lo es. Configurar con las del contrato
# vigente del proveedor para que COSTO_TOTAL signifique algo.
COSTO_ENTRADA_POR_1M = float(os.getenv("LLM_COSTO_ENTRADA_POR_1M", "0"))
COSTO_SALIDA_POR_1M = float(os.getenv("LLM_COSTO_SALIDA_POR_1M", "0"))


def registrar_uso_tokens(entrada: int, salida: int) -> None:
    TOKENS_TOTAL.labels(tipo="entrada").inc(entrada)
    TOKENS_TOTAL.labels(tipo="salida").inc(salida)
    costo = (entrada / 1_000_000) * COSTO_ENTRADA_POR_1M + (salida / 1_000_000) * COSTO_SALIDA_POR_1M
    if costo:
        COSTO_TOTAL.inc(costo)


# ─── Instrumentación de nodos ─────────────────────────────────────────────────

def medir_nodo(nombre: str, fn):
    """
    Envuelve un nodo del grafo para cronometrarlo y contar sus errores.

    Delega siempre en la función original y no altera su valor de retorno: si esto
    cambiara el comportamiento del grafo, dejaría de medir el sistema real.
    """
    @wraps(fn)
    def envuelto(state):
        inicio = time.perf_counter()
        try:
            resultado = fn(state)
        except Exception:
            ERRORES_TOTAL.labels(componente=nombre).inc()
            NODO_DURACION.labels(nodo=nombre).observe(time.perf_counter() - inicio)
            raise
        duracion = time.perf_counter() - inicio
        NODO_DURACION.labels(nodo=nombre).observe(duracion)
        logger.bind(nodo=nombre, duracion_s=round(duracion, 3)).info(f"[NODO] {nombre} completado")
        return resultado

    return envuelto
