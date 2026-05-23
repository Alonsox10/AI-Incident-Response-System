from state.state import IncidentState


# Esta función es el router del grafo, se encarga de decidir a que nodo ir dependiendo del estado actual
def router(state: IncidentState):

    return state["next_agent"]