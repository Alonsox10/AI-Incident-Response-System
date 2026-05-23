from langgraph.graph import StateGraph, END
from state.state import IncidentState
from langgraph.prebuilt import ToolNode
from agents.recomendation_agent import recomendation_agent
from tools.incidente_tools import search_incident_by_category, insert_incident
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from dotenv import load_dotenv
from agents.orchestrator_agent import orchestrator_agent
from graphs.router import router
from agents.classifier_agent import classifier_agent
import os

load_dotenv(override=True)

URI = os.getenv("POSTGRES_URL")
if not URI:
    raise ValueError("La URL de PostgreSQL no está configurada en las variables de entorno.")


# Define los nodos del grafo y sus transiciones
graph = StateGraph(IncidentState)
graph.add_node("orchestrator", orchestrator_agent)
graph.set_entry_point("orchestrator") # El nodo de entrada es el orquestador
graph.add_node("classifier", classifier_agent)
graph.add_node("recommendation",recomendation_agent)
tool_node = ToolNode([search_incident_by_category, insert_incident])
graph.add_node("tools", tool_node)

source_node = "orchestrator"

routing_function = router

# Defina las rutas del grafo
routes = {
    "classifier":"classifier",
    "recommendation":"recommendation",
    "end":END
}

graph.add_edge("classifier", "orchestrator")
graph.add_edge("recommendation", "tools")
graph.add_edge("tools", END)


# Agrega las transiciones condicionales al grafo utilizando la función de enrutamiento
graph.add_conditional_edges(source_node, routing_function, routes)



# Crea las tablas necesarias con el checkpointer sincrono
connection = Connection.connect(URI, autocommit=True)
checkpointer = PostgresSaver(connection)
checkpointer.setup()
app = graph.compile(checkpointer=checkpointer)


