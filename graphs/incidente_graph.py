from langgraph.graph import StateGraph, END
from state.state import IncidentState
from langgraph.prebuilt import ToolNode
from agents.recomendation_agent import recomendation_agent
from tools.incidente_tools import search_incident_by_category, insert_incident
from tools.rag_tools import search_knowledge_base_rag, search_similar_incidents_rag
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from dotenv import load_dotenv
from agents.orchestrator_agent import orchestrator_agent
from graphs.router import router
from agents.classifier_agent import classifier_agent
from database.vector_db import initialize_vector_tables
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
graph.add_node("orchestrator", orchestrator_agent)
graph.set_entry_point("orchestrator")
graph.add_node("classifier", classifier_agent)
graph.add_node("recommendation", recomendation_agent)

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
    "end": END,
}

graph.add_edge("classifier", "orchestrator")
graph.add_edge("tools", "recommendation")
graph.add_conditional_edges("recommendation", recommendation_router, {"tools": "tools", END: END})
graph.add_conditional_edges(source_node, routing_function, routes)


# Inicializar el checkpointer y las tablas vectoriales al arrancar
connection = Connection.connect(URI, autocommit=True)
checkpointer = PostgresSaver(connection)
checkpointer.setup()

initialize_vector_tables()

app = graph.compile(checkpointer=checkpointer)
