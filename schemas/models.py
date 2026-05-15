from pydantic import BaseModel
from typing import List


class IncidentClassification(BaseModel):
    category: str
    priority: str
    possible_causes: List[str]
    recommendations: List[str]
