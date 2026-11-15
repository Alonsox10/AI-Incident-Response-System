"""
Jerarquía de excepciones de dominio.

El objetivo no es tener más clases de error, es separar dos cosas que antes iban
juntas: **lo que se le dice al cliente** y **lo que se registra en el log**. Hasta la
Fase 2 cada endpoint hacía `HTTPException(500, detail=str(e))`, lo que devolvía al
cliente el texto crudo de la excepción — mensajes de psycopg con nombres de tabla,
rutas del filesystem, fragmentos de SQL.

Ahora cada excepción lleva tres datos: el `http_status` que le corresponde, un
`codigo` estable que el cliente puede programar, y un `mensaje_publico` escrito para
leerse. El detalle técnico vive solo en el log, correlacionado por `error_id`.

Las excepciones de agente heredan también de `ValueError` a propósito: era el tipo que
ya levantaban y hay tests que lo afirman. Mantener la compatibilidad evita que este
cambio de infraestructura toque las aserciones de comportamiento de los agentes.
"""
from __future__ import annotations


class ErrorDeDominio(Exception):
    """Base de todos los errores que la aplicación sabe explicar."""

    http_status: int = 500
    codigo: str = "error_interno"
    mensaje_publico: str = "Ocurrió un error procesando la solicitud."
    # Segundos que conviene esperar antes de reintentar. Solo lo usan los errores
    # transitorios; se emite como cabecera `Retry-After`.
    retry_after: int | None = None


# ─── Errores de los agentes del grafo ────────────────────────────────────────

class ErrorDeAgente(ErrorDeDominio, ValueError):
    """
    Fallo dentro de un nodo del grafo.

    Es casi siempre un envoltorio: la causa real (un 429 de OpenAI, un timeout, una
    conexión caída) viaja en `__cause__` porque los agentes levantan con
    `raise ... from e`. Por eso el handler de `main.py` no mira solo el tipo de la
    excepción que recibe, sino toda la cadena de causas.
    """

    codigo = "error_de_agente"
    mensaje_publico = "No se pudo completar el análisis del incidente."


class ErrorDelOrquestador(ErrorDeAgente):
    codigo = "error_orquestador"


class ErrorDelClasificador(ErrorDeAgente):
    codigo = "error_clasificador"


class ErrorDeRecomendacion(ErrorDeAgente):
    codigo = "error_recomendacion"


class ErrorDeFAQ(ErrorDeAgente):
    codigo = "error_faq"


# ─── Errores de dependencias externas ────────────────────────────────────────

class ErrorDeProveedorLLM(ErrorDeDominio):
    """
    El proveedor del modelo no respondió: rate limit, timeout o corte de red.

    Va a **503 y no a 500** porque la diferencia es operativamente enorme: un 500 le
    dice al cliente "tu petición está mal, no la repitas" y un 503 con `Retry-After`
    le dice "no es tu culpa, vuelve en N segundos". Con la cuota del proveedor como
    techo real del sistema, este es el error más frecuente bajo carga.
    """

    http_status = 503
    codigo = "proveedor_no_disponible"
    mensaje_publico = "El servicio de análisis está saturado. Reintenta en unos segundos."
    retry_after = 10


class ErrorDeCuotaLLM(ErrorDeProveedorLLM):
    """Crédito agotado: no es transitorio y reintentar no sirve de nada."""

    http_status = 503
    codigo = "cuota_agotada"
    mensaje_publico = "El servicio de análisis no está disponible temporalmente."
    retry_after = None


class ErrorDeBaseDeDatos(ErrorDeDominio):
    """Postgres no está accesible, o el pool se agotó esperando una conexión."""

    http_status = 503
    codigo = "base_no_disponible"
    mensaje_publico = "El servicio no está disponible temporalmente. Reintenta en unos segundos."
    retry_after = 5


class PresupuestoDeTiempoAgotado(ErrorDeDominio):
    """
    El grafo superó el presupuesto total de tiempo.

    Existe porque los timeouts por llamada no acotan el total: un workflow hace 5-6
    llamadas al LLM y 3 de embeddings, así que con `timeout=30` en cada una el peor
    caso teórico pasa de cuatro minutos. Este tope corta el workflow completo.
    """

    http_status = 503
    codigo = "presupuesto_agotado"
    mensaje_publico = "El análisis tardó más de lo permitido. Reintenta en unos segundos."
    retry_after = 15


# ─── Errores atribuibles al cliente ──────────────────────────────────────────

class ErrorDeEntrada(ErrorDeDominio):
    http_status = 400
    codigo = "entrada_invalida"
    mensaje_publico = "La solicitud no es válida."


class NoAutenticado(ErrorDeDominio):
    http_status = 401
    codigo = "no_autenticado"
    mensaje_publico = "Credenciales ausentes o inválidas."


class SinPermiso(ErrorDeDominio):
    http_status = 403
    codigo = "sin_permiso"
    mensaje_publico = "No tienes permiso para esta operación."


# ─── Traducción de excepciones ajenas ────────────────────────────────────────

def _cadena_de_causas(exc: BaseException, limite: int = 10) -> list[BaseException]:
    """La excepción y sus causas, de la más externa a la original."""
    cadena: list[BaseException] = []
    actual: BaseException | None = exc
    while actual is not None and len(cadena) < limite:
        cadena.append(actual)
        actual = actual.__cause__ or actual.__context__
    return cadena


def _nombres(cadena: list[BaseException]) -> set[str]:
    """Nombres de todas las clases involucradas, incluidas las heredadas."""
    nombres = set()
    for e in cadena:
        for clase in type(e).__mro__:
            nombres.add(clase.__name__)
    return nombres


def clasificar(exc: BaseException) -> ErrorDeDominio:
    """
    Convierte cualquier excepción en el `ErrorDeDominio` que le corresponde.

    La clasificación se hace **por toda la cadena de causas**, no por el tipo de la
    excepción recibida: lo que llega desde el grafo es casi siempre un
    `ErrorDeAgente`, y el dato que decide el status HTTP (un 429, un timeout, una
    conexión caída) está varios niveles más abajo.

    Se identifican los tipos por nombre en vez de importar `openai` y `psycopg` acá:
    así este módulo no arrastra el SDK del proveedor ni se rompe si alguna de esas
    librerías reorganiza sus excepciones.
    """
    cadena = _cadena_de_causas(exc)

    # Un error de dominio ya clasificado se respeta, salvo que sea el envoltorio
    # genérico del agente: ahí vale la pena seguir buscando la causa real.
    for e in cadena:
        if isinstance(e, ErrorDeDominio) and not isinstance(e, ErrorDeAgente):
            return e

    nombres = _nombres(cadena)
    textos = " ".join(str(e).lower() for e in cadena)

    if "RateLimitError" in nombres:
        # insufficient_quota llega como 429 igual que un rate limit, pero no es
        # transitorio: reintentar no lo arregla y no debe anunciar Retry-After.
        if "insufficient_quota" in textos or "exceeded your current quota" in textos:
            return ErrorDeCuotaLLM()
        return ErrorDeProveedorLLM()

    if nombres & {"APITimeoutError", "APIConnectionError", "APIStatusError", "APIError", "OpenAIError"}:
        return ErrorDeProveedorLLM()

    if nombres & {"PoolTimeout", "OperationalError", "InterfaceError", "AdminShutdown"}:
        return ErrorDeBaseDeDatos()

    if "the pool is already closed" in textos or "pool is closed" in textos:
        return ErrorDeBaseDeDatos()

    if nombres & {"TimeoutError", "CancelledError"}:
        return PresupuestoDeTiempoAgotado()

    # Nada reconocible: 500 con mensaje genérico. El detalle queda en el log.
    for e in cadena:
        if isinstance(e, ErrorDeAgente):
            return e
    return ErrorDeDominio()
