
from langgraph.graph import MessagesState

class IncidentState(MessagesState):
    user_input: str
    incident_category: str
    priority: str
    diagnostic_message: list[str]