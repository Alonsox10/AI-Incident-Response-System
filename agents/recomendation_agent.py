import time
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
            tool_names = [m.name for m in messages if isinstance(m, ToolMessage)]
            logger.info(f"[RECOMENDACION] Segunda llamada — sintetizando respuesta | herramientas ejecutadas={tool_names}")
            message_state = [SystemMessage(content=prompt)] + list(messages)
        else:
            input_user = messages[-1].content
            category = state["category"]
            priority = state["priority"]
            logger.info(
                f"[RECOMENDACION] Primera llamada — solicitando herramientas RAG | "
                f"categoria={category} | prioridad={priority}"
            )
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

        inicio = time.perf_counter()
        response = llm_bind_tools.invoke(message_state)
        duracion = time.perf_counter() - inicio

        if has_tool_results:
            logger.info(f"[RECOMENDACION] Respuesta generada | largo={len(response.content)} chars | tiempo={duracion:.2f}s")
        else:
            tool_calls = [tc["name"] for tc in response.tool_calls] if response.tool_calls else []
            logger.info(f"[RECOMENDACION] Herramientas solicitadas={tool_calls} | tiempo={duracion:.2f}s")

        return {
            "messages": [response],
            "recommendations": response.content,
            "current_step": "recommendation_done",
        }
    except Exception as e:
        logger.error(f"Error en el agente de recomendación: {e}")
        raise ValueError("Ocurrió un error en el agente de recomendación.")
