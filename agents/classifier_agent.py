from state.state import IncidentState
from models.llm import llm
from schemas.models import IncidentClassification

# Configura el modelo para que devuelva una salida estructurada
llm_structured = llm.with_structured_output(IncidentClassification)

with open("prompt/classify_agent.md", "r") as f:
    read = f.read()

async def classify_agent(state: IncidentState):
    user_input = state["user_input"]

    full_prompt = f"""
    {read}
    User_incident:
    {user_input}
    """

    response = await llm_structured.ainvoke(full_prompt)
    return {
        "incident_category": response.category,
        "priority": response.priority
    }

