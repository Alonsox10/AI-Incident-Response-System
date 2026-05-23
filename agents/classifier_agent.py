
from models.llm import llm
from loguru import logger
from langchain_core.messages import SystemMessage, HumanMessage
from state.state import IncidentState
from schemas.models import IncidentClassificationOutput

# Configura el modelo para que devuelva una salida estructurada
llm_structured = llm.with_structured_output(IncidentClassificationOutput)


def classifier_agent(state: IncidentState):
    try:
        with open("prompt/classify_agent.md", "r", encoding="utf-8") as f:
            prompt = f.read()

        #Ultimo mensaje del usuario
        user_input = state["messages"][-1].content

        message_state = [
            SystemMessage(content=prompt),
            HumanMessage(content=user_input)
        ]

        response = llm_structured.invoke(message_state)
        print("Classifier agent ejecutado")
        return {
            "category": response.category,
            "priority": response.priority,
            "possible_causes": response.possible_causes,
            "current_step": "classifier_done"
        }
    except Exception as e:
        logger.error(f"Error en el agente clasificador: {e}")
        raise ValueError("Ocurrió un error en el agente clasificador.")

    
