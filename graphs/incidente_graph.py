from langgraph.graph import StateGraph, END
from state.state import IncidentState
from langgraph.prebuilt import ToolNode
from agents.recomendation_agent import recomendation_agent
from tools.incidente_tools import search_incident_by_category, insert_incident
from tools.rag_tools import search_knowledge_base_rag, search_similar_incidents_rag
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from dotenv import load_dotenv
from agents.orchestrator_agent import orchestrator_agent
from graphs.router import router
from agents.classifier_agent import classifier_agent
from agents.faq_agent import faq_agent
from database.db import get_pool
from service.observability import medir_nodo
from langchain_core.messages import AIMessage
import os


def recommendation_router(state: IncidentState):
    messages = state.get("messages", [])
    last_message = messages[-1] if messages else None
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return END

load_dotenv(override=True)

URI = os.getenv("POSTGRES_URL")
if not URI:
    raise ValueError("La URL de PostgreSQL no está configurada en las variables de entorno.")


# Define los nodos del grafo y sus transiciones
graph = StateGraph(IncidentState)
# Cada nodo se registra envuelto en `medir_nodo`, que lo cronometra y cuenta sus
# errores sin alterar su comportamiento. Se hace acá y no dentro de cada agente
# para tener un solo punto de instrumentación que cubra también los nodos futuros.
graph.add_node("orchestrator", medir_nodo("orchestrator", orchestrator_agent))
graph.set_entry_point("orchestrator")
graph.add_node("classifier", medir_nodo("classifier", classifier_agent))
graph.add_node("recommendation", medir_nodo("recommendation", recomendation_agent))
graph.add_node("faq", medir_nodo("faq", faq_agent))

# El ToolNode ahora incluye las dos herramientas RAG junto a las herramientas originales
all_tools = [
    search_incident_by_category,
    insert_incident,
    search_knowledge_base_rag,
    search_similar_incidents_rag,
]
tool_node = ToolNode(all_tools)
graph.add_node("tools", tool_node)

source_node = "orchestrator"
routing_function = router

routes = {
    "classifier": "classifier",
    "recommendation": "recommendation",
    "faq": "faq",
    "end": END,
}

graph.add_edge("classifier", "orchestrator")
# El nodo de FAQ resuelve siempre en una sola pasada: no pasa por tools ni por un router condicional
graph.add_edge("faq", END)
graph.add_edge("tools", "recommendation")
graph.add_conditional_edges("recommendation", recommendation_router, {"tools": "tools", END: END})
graph.add_conditional_edges(source_node, routing_function, routes)


# ─── Compilación ──────────────────────────────────────────────────────────────
#
# Importar este módulo ya no conecta a Postgres ni ejecuta DDL. Antes sí lo hacía, y
# eso significaba que el proceso crasheaba al arrancar si la base no estaba lista
# (CrashLoopBackOff en un orquestador real), que cada réplica lanzaba DDL concurrente
# en cada despliegue, y que el grafo no se podía importar ni testear sin infraestructura.
#
# Ahora el grafo se define al importar —que es puro— y se compila en el `lifespan`.

_app = None


async def iniciar_grafo():
    """
    Compila el grafo con el checkpointer asíncrono. La llama el lifespan de FastAPI.

    El checkpointer comparte el pool del resto de la aplicación en vez de abrir su
    propia conexión: así los checkpoints dejan de serializarse detrás de un único
    socket y se recuperan solos si Postgres se reinicia.
    """
    global _app
    if _app is not None:
        return _app

    pool = await get_pool()
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    _app = graph.compile(checkpointer=checkpointer)
    return _app


def get_app():
    """El grafo compilado. Falla con un mensaje claro si nadie llamó a `iniciar_grafo`."""
    if _app is None:
        raise RuntimeError(
            "El grafo no está compilado. Llama a `await iniciar_grafo()` primero "
            "(el lifespan de FastAPI lo hace al arrancar)."
        )
    return _app


def grafo_listo() -> bool:
    """Para el chequeo de readiness, sin provocar la compilación."""
    return _app is not None
