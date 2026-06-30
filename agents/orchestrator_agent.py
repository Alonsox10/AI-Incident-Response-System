from loguru import logger
from models.llm import llm
from langchain_core.messages import SystemMessage, HumanMessage
from state.state import IncidentState
from schemas.models import OrquestatorOutput


llm_structured = llm.with_structured_output(OrquestatorOutput)

def orchestrator_agent(state: IncidentState):
    try:
        with open("prompt/orquestator.md", "r", encoding="utf-8") as f:
            prompt = f.read()

        messages      = state["messages"]
        user_input    = messages[-1].content
        category      = state.get("category")
        priority      = state.get("priority")
        recommendations = state.get("recommendations")
        current_step  = state.get("current_step")

        # Construir historial de los últimos 3 turnos del usuario para contexto
        mensajes_usuario = [m for m in messages[:-1] if isinstance(m, HumanMessage)]
        historial = ""
        if mensajes_usuario:
            historial = "Historial de mensajes anteriores del usuario:\n"
            for msg in mensajes_usuario[-3:]:
                historial += f"  - {msg.content[:150]}\n"

        workflow_context = f"""
        Estado actual del workflow:

        Category: {category}
        Priority: {priority}
        Current step: {current_step}

        {historial}
        """

        message_state = [
            SystemMessage(content=prompt),
            HumanMessage(content=f"Usuario: {user_input}\n{workflow_context}"),
        ]

        response = llm_structured.invoke(message_state)
        logger.info(f"[ORQUESTADOR] Decision: {response.next_agent} | current_step={current_step} | categoria={category}")
        return {"next_agent": response.next_agent}
    except Exception as e:
        logger.error(f"Error en el agente orquestador: {e}")
        raise ValueError("Ocurrió un error en el agente orquestador.")