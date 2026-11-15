"""
Tests unitarios de la lógica de routing que vive en código (no en un prompt).

`recommendation_router` es la que gobierna la doble pasada del agente de
recomendación: primera pasada pide las tools, el router las despacha al `ToolNode`,
y la segunda pasada sintetiza. Si devolviera `END` con tool_calls pendientes, el
RAG no se consultaría nunca y la respuesta se generaría sin contexto — sin error
visible, solo peores recomendaciones.

`get_app`/`grafo_listo` son el contrato de arranque: el grafo se compila en el
lifespan, no al importar.
"""
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END

import graphs.incidente_graph as ig
from graphs.incidente_graph import recommendation_router
from graphs.router import router


TOOL_CALL = {
    "id": "call_1",
    "name": "search_knowledge_base_rag",
    "args": {"query": "el backend no responde"},
    "type": "tool_call",
}


# ---------------------------------------------------------------------------
# recommendation_router: la doble pasada
# ---------------------------------------------------------------------------

def test_con_tool_calls_pendientes_despacha_al_nodo_de_tools():
    state = {"messages": [AIMessage(content="", tool_calls=[TOOL_CALL])]}
    assert recommendation_router(state) == "tools"


def test_varias_tool_calls_en_paralelo_tambien_van_a_tools():
    """La primera pasada pide las tres tools de una; una sola vuelta al ToolNode."""
    calls = [
        dict(TOOL_CALL, id="c1", name="search_knowledge_base_rag"),
        dict(TOOL_CALL, id="c2", name="search_similar_incidents_rag"),
        dict(TOOL_CALL, id="c3", name="insert_incident"),
    ]
    state = {"messages": [AIMessage(content="", tool_calls=calls)]}
    assert recommendation_router(state) == "tools"


def test_la_segunda_pasada_sin_tool_calls_termina():
    """Respuesta sintetizada: ya no pide tools, el workflow cierra."""
    state = {
        "messages": [
            HumanMessage(content="el backend no responde"),
            AIMessage(content="", tool_calls=[TOOL_CALL]),
            ToolMessage(content="doc relevante", tool_call_id="call_1", name="search_knowledge_base_rag"),
            AIMessage(content="Reinicia el servicio y revisa los logs."),
        ]
    }
    assert recommendation_router(state) == END


def test_solo_mira_el_ultimo_mensaje():
    """Una tool_call ya resuelta en el historial no debe reenviar al ToolNode:
    eso ejecutaría las tools dos veces y registraría el incidente duplicado."""
    state = {
        "messages": [
            AIMessage(content="", tool_calls=[TOOL_CALL]),
            ToolMessage(content="ya ejecutada", tool_call_id="call_1", name="search_knowledge_base_rag"),
        ]
    }
    assert recommendation_router(state) == END


def test_un_historial_vacio_termina_en_vez_de_reventar():
    assert recommendation_router({"messages": []}) == END
    assert recommendation_router({}) == END


# ---------------------------------------------------------------------------
# router del orquestador
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("destino", ["classifier", "recommendation", "faq", "end"])
def test_el_router_devuelve_la_decision_del_orquestador(destino):
    """Las cuatro claves del routing deben estar declaradas en el grafo real;
    si el Literal de OrquestatorOutput crece y el grafo no, el grafo revienta
    en ejecución con una decisión que no sabe enrutar."""
    assert router({"next_agent": destino}) == destino
    assert destino in ig.routes


# ---------------------------------------------------------------------------
# Contrato de arranque
# ---------------------------------------------------------------------------

def test_sin_compilar_get_app_falla_con_un_mensaje_accionable(monkeypatch):
    monkeypatch.setattr(ig, "_app", None)

    with pytest.raises(RuntimeError) as exc:
        ig.get_app()

    assert "iniciar_grafo" in str(exc.value)


def test_grafo_listo_refleja_el_estado_sin_compilar_nada(monkeypatch):
    """El chequeo de readiness no debe tener el efecto secundario de compilar:
    si lo tuviera, /ready daría verde abriendo el pool que decía estar probando."""
    monkeypatch.setattr(ig, "_app", None)
    assert ig.grafo_listo() is False

    monkeypatch.setattr(ig, "_app", object())
    assert ig.grafo_listo() is True
    # Y get_app devuelve ese mismo objeto, sin recompilar.
    assert ig.get_app() is ig._app
