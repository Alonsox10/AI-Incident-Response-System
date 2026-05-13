from langgraph.graph import StateGraph
from state.state import IncidentState
from agents.classifier_agent import classify_agent
from langgraph.prebuilt import tool_node , tools_condition, ToolNode
from tools.incidente_tools import search_incident_by_category, insert_incident


# Define los nodos del grafo y sus transiciones
graph = StateGraph(IncidentState)
graph.add_node("classifier", classify_agent)
graph.set_entry_point("classifier") # El nodo de entrada es el clasificador
# Registra las tools en el grafo
tool_node = ToolNode([search_incident_by_category, insert_incident])

graph.add_node("tools", tool_node)
graph.add_conditional_edges("classifier", tools_condition)
graph.add_edge("tools", "classifier")


app = graph.compile()

