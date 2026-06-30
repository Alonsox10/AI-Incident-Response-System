import time
from models.llm import llm
from loguru import logger
from langchain_core.messages import SystemMessage, HumanMessage
from state.state import IncidentState
from schemas.models import IncidentClassificationOutput

llm_structured = llm.with_structured_output(IncidentClassificationOutput)


def classifier_agent(state: IncidentState):
    try:
        with open("prompt/classify_agent.md", "r", encoding="utf-8") as f:
            prompt = f.read()

        user_input = state["messages"][-1].content
        logger.info(f"[CLASIFICADOR] Clasificando incidente | input='{user_input[:80]}'")

        message_state = [
            SystemMessage(content=prompt),
            HumanMessage(content=user_input)
        ]

        inicio = time.perf_counter()
        response = llm_structured.invoke(message_state)
        duracion = time.perf_counter() - inicio

        logger.info(
            f"[CLASIFICADOR] Resultado: categoria={response.category} | "
            f"prioridad={response.priority} | causas={len(response.possible_causes)} | "
            f"tiempo={duracion:.2f}s"
        )
        return {
            "category": response.category,
            "priority": response.priority,
            "possible_causes": response.possible_causes,
            "current_step": "classifier_done"
        }
    except Exception as e:
        logger.error(f"Error en el agente clasificador: {e}")
        raise ValueError("Ocurrió un error en el agente clasificador.")

    
