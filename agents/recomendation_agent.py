from loguru import logger
from langchain_core.messages import SystemMessage , HumanMessage
from models.llm import llm_bind_tools
from state.state import IncidentState




def recomendation_agent(state: IncidentState):
    try:
        with open("prompt/recomendation_agent.md", "r", encoding="utf-8") as f:
            prompt = f.read()

        #Obetner informacion del state
        input_user = state["messages"][-1].content

        category = state["category"]

        priority = state["priority"]


        # Construir el contexto para el agente de recomendación
        context = f"""
        Incidente:
        {input_user}

        Categoría:
        {category}

        Prioridad:
        {priority}

        """

        message_state = [
            SystemMessage(content=prompt),
            HumanMessage(content=context)
        ]

        response = llm_bind_tools.invoke(message_state)
        print("Recomendation agent ejecutado")
        return {
            "messages": [response],
            "recommendations": response.content,
            "current_step": "recommendation_done"
        }
    except Exception as e:
        logger.error(f"Error en el agente de recomendación: {e}")
        raise ValueError("Ocurrió un error en el agente de recomendación.")