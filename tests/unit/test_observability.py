"""
Tests unitarios de `medir_nodo`, el único punto de instrumentación del grafo.

Dos invariantes que el resto de la suite no vigilaba:

1. **Rechaza nodos síncronos.** Es la guarda que sostiene toda la decisión de la
   fase 1: un nodo `def` en vez de `async def` lo delega LangGraph al threadpool de
   AnyIO y reintroduce el techo de ~40 concurrentes sin que nada falle. Como el
   envoltorio no cambia el comportamiento observable del nodo, ninguna otra prueba
   podría delatar la regresión — solo esta.
2. **No altera el resultado del nodo.** Si lo alterara, mediría un sistema distinto
   del que corre en producción.
"""
import pytest
from prometheus_client import REGISTRY

from service.observability import medir_nodo


def _errores_de(componente):
    """Valor actual del contador de errores para un componente (0 si no tiene muestras)."""
    valor = REGISTRY.get_sample_value(
        "errores_total", {"componente": componente}
    )
    return valor if valor is not None else 0.0


# ---------------------------------------------------------------------------
# Invariante 1: solo nodos asíncronos
# ---------------------------------------------------------------------------

def test_un_nodo_sincrono_es_rechazado_al_registrarlo():
    """Un nodo `def` no llega a ejecutarse nunca: falla al envolverlo."""
    def nodo_sincrono(state):
        return {"ok": True}

    with pytest.raises(TypeError) as exc:
        medir_nodo("nodo_sincrono", nodo_sincrono)

    # El mensaje tiene que nombrar el nodo culpable y el motivo, o el fallo es inútil
    # al arrancar el servicio con media docena de nodos registrados.
    assert "nodo_sincrono" in str(exc.value)
    assert "async def" in str(exc.value)


def test_una_lambda_tambien_es_rechazada():
    """La guarda mira si es corrutina, no si tiene nombre."""
    with pytest.raises(TypeError):
        medir_nodo("lambda_node", lambda state: state)


def test_un_nodo_asincrono_se_acepta():
    async def nodo_async(state):
        return {}

    envuelto = medir_nodo("nodo_async", nodo_async)
    assert envuelto is not nodo_async
    # `@wraps` debe conservar la identidad del nodo original: LangGraph y los
    # tracebacks lo usan para nombrar el paso.
    assert envuelto.__name__ == "nodo_async"


# ---------------------------------------------------------------------------
# Invariante 2: transparencia respecto del nodo original
# ---------------------------------------------------------------------------

async def test_devuelve_exactamente_lo_que_devolvio_el_nodo():
    esperado = {"category": "Redes", "current_step": "classifier_done"}

    async def nodo(state):
        return esperado

    resultado = await medir_nodo("transparente", nodo)({"messages": []})

    # Mismo objeto, no una copia equivalente: el envoltorio no debe tocar el estado.
    assert resultado is esperado


async def test_le_pasa_el_estado_al_nodo_sin_modificarlo():
    recibido = {}

    async def nodo(state):
        recibido["state"] = state
        return {}

    estado = {"messages": ["x"], "current_step": None}
    await medir_nodo("pasamanos", nodo)(estado)

    assert recibido["state"] is estado


# ---------------------------------------------------------------------------
# Errores: se cuentan y se relanzan intactos
# ---------------------------------------------------------------------------

async def test_un_fallo_del_nodo_se_relanza_sin_envolver():
    class ErrorDePrueba(Exception):
        pass

    async def nodo_que_falla(state):
        raise ErrorDePrueba("boom")

    envuelto = medir_nodo("nodo_roto", nodo_que_falla)

    # El envoltorio no debe tragarse ni reempaquetar el error: el handler de main.py
    # recorre la cadena de causas para distinguir un 429 del proveedor de un fallo propio.
    with pytest.raises(ErrorDePrueba, match="boom"):
        await envuelto({"messages": []})


async def test_un_fallo_del_nodo_incrementa_el_contador_de_errores():
    async def nodo_que_falla(state):
        raise RuntimeError("fallo medido")

    envuelto = medir_nodo("nodo_contado", nodo_que_falla)
    antes = _errores_de("nodo_contado")

    with pytest.raises(RuntimeError):
        await envuelto({"messages": []})

    assert _errores_de("nodo_contado") == antes + 1


async def test_un_nodo_exitoso_no_incrementa_el_contador_de_errores():
    async def nodo_ok(state):
        return {}

    envuelto = medir_nodo("nodo_sano", nodo_ok)
    antes = _errores_de("nodo_sano")

    await envuelto({"messages": []})

    assert _errores_de("nodo_sano") == antes


async def test_la_duracion_se_observa_tanto_en_exito_como_en_fallo():
    """El histograma debe registrar la pasada incluso cuando el nodo revienta;
    si no, un nodo que siempre falla aparece como un nodo que nunca corre."""
    async def nodo_ok(state):
        return {}

    async def nodo_malo(state):
        raise ValueError("x")

    await medir_nodo("medido_ok", nodo_ok)({"messages": []})
    with pytest.raises(ValueError):
        await medir_nodo("medido_malo", nodo_malo)({"messages": []})

    muestras_ok = REGISTRY.get_sample_value(
        "agente_nodo_duracion_segundos_count", {"nodo": "medido_ok"}
    )
    muestras_malo = REGISTRY.get_sample_value(
        "agente_nodo_duracion_segundos_count", {"nodo": "medido_malo"}
    )

    assert muestras_ok == 1.0
    assert muestras_malo == 1.0
