import os
from loguru import logger
from models.llm import llm
from langchain_core.messages import SystemMessage, HumanMessage
from state.state import IncidentState
from schemas.models import OrquestatorOutput
from service.embedding_service import get_embedding
from database.vector_db import search_faqs


llm_structured = llm.with_structured_output(OrquestatorOutput)

# Umbral para saltarse al LLM y enrutar directo a FAQ. Deliberadamente más alto que el
# umbral con que el agente de FAQ responde (0.75): ahí caen también los parafraseos de
# un síntoma activo ("mi equipo tarda mucho en prender hoy" ≈ 0.74), y esos deben pasar
# por el criterio del orquestador. Este pre-chequeo solo atrapa preguntas ya documentadas.
FAQ_ROUTING_THRESHOLD = float(os.getenv("FAQ_ROUTING_THRESHOLD", "0.85"))


def _coincide_con_faq_documentada(user_input: str) -> float | None:
    """
    Retorna la similitud del mejor match en la tabla faqs si supera FAQ_ROUTING_THRESHOLD,
    o None si no hay coincidencia suficiente.

    Sirve para no dejar la decisión de routing librada a la redacción del mensaje: si la
    pregunta ya está documentada, va a FAQ aunque esté formulada como síntoma activo.
    """
    results = search_faqs(get_embedding(user_input), top_k=1)
    if results and results[0]["similarity"] >= FAQ_ROUTING_THRESHOLD:
        return results[0]["similarity"]
    return None


def orchestrator_agent(state: IncidentState):
    try:
        messages      = state["messages"]
        user_input    = messages[-1].content
        category      = state.get("category")
        priority      = state.get("priority")
        recommendations = state.get("recommendations")
        current_step  = state.get("current_step")

        # Solo al inicio del workflow: una vez clasificado, el routing lo decide current_step
        if current_step is None:
            similitud = _coincide_con_faq_documentada(user_input)
            if similitud is not None:
                logger.info(f"[ORQUESTADOR] Decision: faq | match documentado={similitud:.0%} | sin llamada al LLM")
                return {"next_agent": "faq"}

        with open("prompt/orquestator.md", "r", encoding="utf-8") as f:
            prompt = f.read()

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