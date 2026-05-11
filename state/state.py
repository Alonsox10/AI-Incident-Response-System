from typing import TypedDict


class IncidentState(TypedDict):
    user_input: str
    incident_category: str
    priority: str
    diagnostic_message: list[str]