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

        # Obtiene que quiere el usuario 
        user_input = state["messages"][-1].content

        category = state.get("category")

        priority = state.get("priority")

        recommendations = state.get("recommendations")

        current_step = state.get("current_step")

        workflow_context = f"""
        Estado actual del workflow:

        Category:
        {category}

        Priority:
        {priority}

        Recommendations:
        {recommendations}

        Current step:
        {current_step}
        """

        message_state = [
            SystemMessage(content=prompt),
            HumanMessage(content= f"""
                Usuario: {user_input} 
                {workflow_context}
                """
            )
        ]

        response = llm_structured.invoke(message_state)
        print("ORCHESTRATOR EJECUTADO")
        return {
            "next_agent": response.next_agent
        }
    except Exception as e:
        logger.error(f"Error en el agente orquestador: {e}")
        raise ValueError("Ocurrió un error en el agente orquestador.")