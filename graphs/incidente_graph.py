from langgraph.graph import StateGraph
from state.state import IncidentState
from agents.classifier_agent import classify_agent
from langgraph.prebuilt import  tools_condition, ToolNode
from tools.incidente_tools import search_incident_by_category, insert_incident
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from dotenv import load_dotenv
import os

load_dotenv(override=True)

URI = os.getenv("POSTGRES_URL")
if not URI:
    raise ValueError("La URL de PostgreSQL no está configurada en las variables de entorno.")


# Define los nodos del grafo y sus transiciones
graph = StateGraph(IncidentState)
graph.add_node("classifier", classify_agent)
graph.set_entry_point("classifier") # El nodo de entrada es el clasificador
# Registra las tools en el grafo
tool_node = ToolNode([search_incident_by_category, insert_incident])

graph.add_node("tools", tool_node)
graph.add_conditional_edges("classifier", tools_condition)
graph.add_edge("tools", "classifier")

# Crea las tablas necesarias con el checkpointer sincrono
connection = Connection.connect(URI, autocommit=True)
checkpointer = PostgresSaver(connection)
checkpointer.setup()
app = graph.compile(checkpointer=checkpointer)


