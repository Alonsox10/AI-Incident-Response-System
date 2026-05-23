from pydantic import BaseModel
from typing import List, Literal


class IncidentClassificationOutput(BaseModel):
    category: str
    priority: str
    possible_causes: List[str]



class RecommendationOutput(BaseModel):

    possible_causes: List[str]
    recommendations: List[str]


class OrquestatorOutput(BaseModel):
    next_agent: Literal["classifier", "recommendation", "end"]



