from langgraph.graph import StateGraph , START , END
from state.state import IncidentState
from agents.classifier_agent import classify_agent


# Define los nodos del grafo y sus transiciones
graph = StateGraph(IncidentState)
graph.add_node("classifier", classify_agent)
graph.set_entry_point("classifier") # El nodo de entrada es el clasificador
graph.add_edge("classifier", END)


app = graph.compile()