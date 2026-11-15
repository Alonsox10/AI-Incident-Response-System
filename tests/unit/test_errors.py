"""
Tests de la jerarquía de excepciones de la Fase 2.

Lo que se verifica acá no es que las clases existan, es que la **clasificación por
cadena de causas** funcione: lo que llega al handler desde el grafo es siempre un
envoltorio (`ErrorDeAgente`), y el dato que decide el status HTTP —un 429 del
proveedor, un pool agotado— está varios niveles más abajo en `__cause__`. Si esta
traducción se rompe, un rate limit vuelve a salir como 500 y el cliente deja de saber
que puede reintentar.

Las excepciones del proveedor se simulan con clases de nombre equivalente en vez de
importar el SDK de OpenAI: `service/errors.py` identifica los tipos por nombre a
propósito, para no arrastrar el SDK ni romperse si reorganiza sus excepciones, y el
test ejercita ese mecanismo tal como es.
"""
import pytest

from service.errors import (
    ErrorDeAgente,
    ErrorDeBaseDeDatos,
    ErrorDeCuotaLLM,
    ErrorDeDominio,
    ErrorDeEntrada,
    ErrorDeFAQ,
    ErrorDelClasificador,
    ErrorDeProveedorLLM,
    PresupuestoDeTiempoAgotado,
    clasificar,
)


# Dobles con los nombres que usa el SDK de OpenAI.
class RateLimitError(Exception):
    pass


class APITimeoutError(Exception):
    pass


class PoolTimeout(Exception):
    pass


def _envuelto_en_agente(causa: Exception) -> ErrorDeAgente:
    """Reproduce lo que hace un agente: envolver con `raise ... from e`."""
    try:
        raise causa
    except Exception as e:
        try:
            raise ErrorDelClasificador("Ocurrió un error en el agente clasificador.") from e
        except ErrorDelClasificador as envuelto:
            return envuelto


# ─── Compatibilidad con lo que ya existía ────────────────────────────────────

def test_los_errores_de_agente_siguen_siendo_value_error():
    """
    Los agentes levantaban `ValueError` y hay tests que lo afirman. Mantener la
    herencia es lo que permite que este cambio de infraestructura no toque las
    aserciones de comportamiento de los cuatro agentes.
    """
    assert issubclass(ErrorDeAgente, ValueError)
    assert isinstance(ErrorDeFAQ("x"), ValueError)


# ─── Clasificación a través de la cadena de causas ───────────────────────────

def test_un_429_del_proveedor_sale_como_503_con_retry_after():
    """El criterio de aceptación de la fase: un 429 de OpenAI no es un 500."""
    dominio = clasificar(_envuelto_en_agente(RateLimitError("429 Too Many Requests")))

    assert isinstance(dominio, ErrorDeProveedorLLM)
    assert dominio.http_status == 503
    assert dominio.retry_after is not None


def test_la_cuota_agotada_no_anuncia_retry_after():
    """
    `insufficient_quota` llega como 429 igual que un rate limit, pero no es
    transitorio: decirle al cliente que reintente en 10 s sería mentirle.
    """
    causa = RateLimitError("Error code: 429 - insufficient_quota: exceeded your current quota")
    dominio = clasificar(_envuelto_en_agente(causa))

    assert isinstance(dominio, ErrorDeCuotaLLM)
    assert dominio.retry_after is None


def test_un_timeout_del_proveedor_sale_como_503():
    dominio = clasificar(_envuelto_en_agente(APITimeoutError("request timed out")))
    assert isinstance(dominio, ErrorDeProveedorLLM)


def test_un_pool_agotado_sale_como_error_de_base():
    dominio = clasificar(_envuelto_en_agente(PoolTimeout("couldn't get a connection")))
    assert isinstance(dominio, ErrorDeBaseDeDatos)
    assert dominio.http_status == 503


def test_el_pool_cerrado_se_reconoce_por_el_mensaje():
    """
    Regresión del bug de la Fase 1: psycopg cierra el pool cuando `open()` agota el
    timeout y toda llamada posterior falla con este mensaje. Es indisponibilidad de
    base, no un error del cliente.
    """
    dominio = clasificar(_envuelto_en_agente(Exception("the pool is already closed")))
    assert isinstance(dominio, ErrorDeBaseDeDatos)


def test_un_timeout_del_presupuesto_sale_como_presupuesto_agotado():
    import asyncio

    dominio = clasificar(_envuelto_en_agente(asyncio.TimeoutError()))
    assert isinstance(dominio, PresupuestoDeTiempoAgotado)


def test_un_error_desconocido_cae_en_500_sin_filtrar_el_mensaje():
    """
    El criterio de que los errores del cliente no lleven texto de excepción: el
    mensaje público es fijo, no se construye con `str(e)`.
    """
    causa = Exception('relation "incidents" does not exist en C:\\app\\database\\db.py')
    dominio = clasificar(_envuelto_en_agente(causa))

    assert dominio.http_status == 500
    assert "incidents" not in dominio.mensaje_publico
    assert "C:\\" not in dominio.mensaje_publico


def test_un_error_de_dominio_ya_clasificado_se_respeta():
    """Si alguien ya decidió el status, `clasificar` no lo reinterpreta."""
    original = ErrorDeEntrada("payload inválido")
    assert clasificar(original) is original


def test_la_cadena_se_recorre_hasta_la_causa_original():
    """
    Dos niveles de envoltorio: el status lo sigue decidiendo la causa raíz. Es el
    caso real, porque el grafo añade sus propias capas por encima del agente.
    """
    interno = _envuelto_en_agente(RateLimitError("429"))
    try:
        raise RuntimeError("fallo del nodo") from interno
    except RuntimeError as e:
        dominio = clasificar(e)

    assert isinstance(dominio, ErrorDeProveedorLLM)


def test_todo_error_de_dominio_declara_los_tres_datos_de_la_respuesta():
    """Contrato con `_responder_error`: sin cualquiera de los tres, la respuesta queda a medias."""
    for clase in (
        ErrorDeDominio,
        ErrorDeAgente,
        ErrorDeProveedorLLM,
        ErrorDeCuotaLLM,
        ErrorDeBaseDeDatos,
        PresupuestoDeTiempoAgotado,
        ErrorDeEntrada,
    ):
        assert isinstance(clase.http_status, int)
        assert clase.codigo
        assert clase.mensaje_publico
