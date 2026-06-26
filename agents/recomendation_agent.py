from loguru import logger
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from models.llm import llm_bind_tools
from state.state import IncidentState


def recomendation_agent(state: IncidentState):
    try:
        with open("prompt/recomendation_agent.md", "r", encoding="utf-8") as f:
            prompt = f.read()

        messages = state["messages"]
        has_tool_results = any(isinstance(m, ToolMessage) for m in messages)

        if has_tool_results:
            # Segunda llamada: el LLM ya tiene los resultados de las herramientas (incluido el contexto RAG), genera la respuesta final
            message_state = [SystemMessage(content=prompt)] + list(messages)
        else:
            # Primera llamada: construir contexto desde el estado y pedir al LLM que ejecute las herramientas RAG e insert
            input_user = messages[-1].content
            category = state["category"]
            priority = state["priority"]

            context = f"""Incidente reportado por el usuario:
{input_user}

Clasificación:
- Categoría: {category}
- Prioridad: {priority}

Instrucciones:
1. Llama a `search_knowledge_base_rag` con la descripción del incidente para recuperar documentación técnica relevante.
2. Llama a `search_similar_incidents_rag` con la descripción del incidente para encontrar resoluciones históricas similares.
3. Llama a `insert_incident` para registrar este nuevo incidente en la base de datos.
Puedes hacer las tres llamadas en paralelo.
"""
            message_state = [
                SystemMessage(content=prompt),
                HumanMessage(content=context),
            ]

        response = llm_bind_tools.invoke(message_state)
        print("Recomendation agent ejecutado")
        return {
            "messages": [response],
            "recommendations": response.content,
            "current_step": "recommendation_done",
        }
    except Exception as e:
        logger.error(f"Error en el agente de recomendación: {e}")
        raise ValueError("Ocurrió un error en el agente de recomendación.")
