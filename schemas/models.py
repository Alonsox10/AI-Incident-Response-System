from pydantic import BaseModel


class IncidentClassification(BaseModel):
    category: str
    priority: str