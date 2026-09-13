import os
import time
from loguru import logger
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from models.llm import llm
from state.state import IncidentState
from service.embedding_service import get_embedding
from database.vector_db import search_faqs


# Por encima de este umbral la FAQ se devuelve tal cual, sin generar texto con el LLM.
# Ajustable con datos reales: si el agente devuelve respuestas exactas que no corresponden,
# subirlo; si casi nunca acierta directo, bajarlo.
FAQ_HIGH_CONFIDENCE_THRESHOLD = float(os.getenv("FAQ_HIGH_CONFIDENCE_THRESHOLD", "0.75"))

SIN_RESULTADOS = (
    "No encontré una pregunta frecuente que coincida con lo que necesitas. "
    "¿Puedes describir el problema con más detalle? Si es algo que te está ocurriendo "
    "ahora mismo, repórtalo como incidente y te doy un diagnóstico completo."
)


def faq_agent(state: IncidentState):
    try:
        messages = state["messages"]
        user_input = messages[-1].content

        logger.info(f"[FAQ] Buscando en la base de FAQs | pregunta='{user_input[:80]}'")
        inicio = time.perf_counter()

        embedding = get_embedding(user_input)
        results = search_faqs(embedding, top_k=3)

        duracion = time.perf_counter() - inicio

        if not results:
            logger.info(f"[FAQ] Sin resultados sobre el umbral minimo | tiempo={duracion:.2f}s")
            return {
                "messages": [AIMessage(content=SIN_RESULTADOS)],
                "recommendations": SIN_RESULTADOS,
                "current_step": "faq_done",
            }

        mejor = results[0]
        logger.info(
            f"[FAQ] {len(results)} candidatos encontrados | "
            f"similitud_max={mejor['similarity']:.0%} | categoria={mejor['category']} | "
            f"tiempo={duracion:.2f}s"
        )

        # Alta confianza: se devuelve la respuesta almacenada sin pasar por el LLM
        if mejor["similarity"] >= FAQ_HIGH_CONFIDENCE_THRESHOLD:
            logger.info(f"[FAQ] Coincidencia directa | pregunta='{mejor['question'][:60]}' | sin llamada al LLM")
            return {
                "messages": [AIMessage(content=mejor["answer"])],
                "recommendations": mejor["answer"],
                "current_step": "faq_done",
            }

        # Baja confianza: una sola llamada al LLM para sintetizar con los candidatos como contexto
        with open("prompt/faq_agent.md", "r", encoding="utf-8") as f:
            prompt = f.read()

        candidatos = "\n\n---\n\n".join(
            f"[FAQ {i} — similitud {r['similarity']:.0%} | categoría: {r['category']}]\n"
            f"Pregunta: {r['question']}\n"
            f"Respuesta: {r['answer']}"
            for i, r in enumerate(results, 1)
        )

        context = f"""Pregunta del usuario:
{user_input}

FAQs recuperadas:

{candidatos}
"""

        message_state = [
            SystemMessage(content=prompt),
            HumanMessage(content=context),
        ]

        inicio_llm = time.perf_counter()
        response = llm.invoke(message_state)
        duracion_llm = time.perf_counter() - inicio_llm

        logger.info(
            f"[FAQ] Respuesta sintetizada | candidatos={len(results)} | "
            f"largo={len(response.content)} chars | tiempo={duracion_llm:.2f}s"
        )

        return {
            "messages": [response],
            "recommendations": response.content,
            "current_step": "faq_done",
        }
    except Exception as e:
        logger.error(f"Error en el agente de FAQs: {e}")
        raise ValueError("Ocurrió un error en el agente de FAQs.")
