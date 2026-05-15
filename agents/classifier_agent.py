from models.llm import llm_bind_tools
from loguru import logger
from langchain_core.messages import SystemMessage
from state.state import IncidentState


def classify_agent(state: IncidentState):
    try:
        with open("prompt/classify_agent.md", "r", encoding="utf-8") as f:
            prompt = f.read()

        messages_state = [
            SystemMessage(content=prompt),
            *state["messages"]
        ]

        response = llm_bind_tools.invoke(messages_state)
        return {"messages": [response]}

    except Exception as e:
        logger.error(f"Error en el agente de clasificación: {e}")
        raise ValueError("Ocurrió un error en el agente de clasificación.")


    
