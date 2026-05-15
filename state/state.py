
from langgraph.graph import MessagesState
from typing import List

class IncidentState(MessagesState):
    category: str
    priority: str
    possible_causes: List[str]
    recommendations: List[str]