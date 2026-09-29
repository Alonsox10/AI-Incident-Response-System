from pydantic import BaseModel
from typing import List, Literal


# Vocabulario cerrado del clasificador. Debe coincidir con las categorías y los criterios
# de prioridad declarados en prompt/classify_agent.md: el prompt guía, el Literal obliga.
# Es lo que mantiene utilizable a search_incident_by_category, que filtra por igualdad exacta
# (`WHERE category = %s`): cualquier variante inventada fragmentaría el histórico en silencio.
IncidentCategory = Literal[
    "Error backend",
    "Error frontend",
    "Infraestructura",
    "Redes",
    "Seguridad",
]

IncidentPriority = Literal["Alta", "Media", "Baja"]


class IncidentClassificationOutput(BaseModel):
    category: IncidentCategory
    priority: IncidentPriority
    possible_causes: List[str]
    # False cuando el mensaje no describe un síntoma concreto sobre el que se pueda
    # diagnosticar. Sin esto el agente inventa un diagnóstico para cualquier entrada:
    # "algo no está funcionando bien" producía un análisis de error HTTP 500.
    informacion_suficiente: bool



class RecommendationOutput(BaseModel):

    possible_causes: List[str]
    recommendations: List[str]


class OrquestatorOutput(BaseModel):
    next_agent: Literal["classifier", "recommendation", "faq", "end"]



