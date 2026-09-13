"""
Tests unitarios para el agente de FAQs.

El faq_agent busca siempre primero contra la tabla `faqs` (no vía tool-calling) y
resuelve por una de tres ramas según la similitud del mejor candidato.
Parcheamos `get_embedding`, `search_faqs` y `llm` tal como los importa el módulo del agente.
"""
import pytest
from unittest.mock import patch
from langchain_core.messages import HumanMessage, AIMessage


def make_state(user_input="¿Cómo se desbloquea una cuenta en Active Directory?"):
    return {
        "messages": [HumanMessage(content=user_input)],
        "category": None,
        "priority": None,
    }


def make_faq(similarity, question="¿Cómo desbloqueo una cuenta?", answer="Usar Unlock-ADAccount."):
    return {
        "id": 1,
        "question": question,
        "answer": answer,
        "category": "Active Directory y usuarios",
        "metadata": {"severity": "Baja"},
        "similarity": similarity,
    }


# ---------------------------------------------------------------------------
# Rama 1: sin resultados sobre el umbral mínimo
# ---------------------------------------------------------------------------

def test_sin_resultados_invita_a_describir_el_problema():
    """Sin candidatos, responde pidiendo más detalle y sin llamar al LLM."""
    with patch("agents.faq_agent.get_embedding", return_value=[0.0] * 1536), \
         patch("agents.faq_agent.search_faqs", return_value=[]), \
         patch("agents.faq_agent.llm") as mock_llm:

        from agents.faq_agent import faq_agent
        result = faq_agent(make_state())

    mock_llm.invoke.assert_not_called()
    assert "incidente" in result["recommendations"].lower()
    assert result["current_step"] == "faq_done"


# ---------------------------------------------------------------------------
# Rama 2: alta confianza — respuesta almacenada, sin generación
# ---------------------------------------------------------------------------

def test_alta_confianza_devuelve_la_respuesta_almacenada_sin_llm():
    """Por encima del umbral, devuelve el answer tal cual y no invoca al LLM."""
    from agents.faq_agent import FAQ_HIGH_CONFIDENCE_THRESHOLD

    faq = make_faq(FAQ_HIGH_CONFIDENCE_THRESHOLD + 0.10, answer="Ejecutar Unlock-ADAccount -Identity usuario.")

    with patch("agents.faq_agent.get_embedding", return_value=[0.0] * 1536), \
         patch("agents.faq_agent.search_faqs", return_value=[faq]), \
         patch("agents.faq_agent.llm") as mock_llm:

        from agents.faq_agent import faq_agent
        result = faq_agent(make_state())

    mock_llm.invoke.assert_not_called()
    assert result["recommendations"] == "Ejecutar Unlock-ADAccount -Identity usuario."
    assert result["messages"][0].content == "Ejecutar Unlock-ADAccount -Identity usuario."
    assert result["current_step"] == "faq_done"


# ---------------------------------------------------------------------------
# Rama 3: baja confianza — síntesis con una sola llamada al LLM
# ---------------------------------------------------------------------------

def test_baja_confianza_sintetiza_con_una_llamada_al_llm():
    """Con candidatos por debajo del umbral, hace exactamente una llamada al LLM."""
    from agents.faq_agent import FAQ_HIGH_CONFIDENCE_THRESHOLD

    faq = make_faq(FAQ_HIGH_CONFIDENCE_THRESHOLD - 0.20)
    mock_response = AIMessage(content="No hay coincidencia exacta, pero esto es lo aplicable.")

    with patch("agents.faq_agent.get_embedding", return_value=[0.0] * 1536), \
         patch("agents.faq_agent.search_faqs", return_value=[faq]), \
         patch("agents.faq_agent.llm") as mock_llm:

        mock_llm.invoke.return_value = mock_response

        from agents.faq_agent import faq_agent
        result = faq_agent(make_state())

    mock_llm.invoke.assert_called_once()
    assert result["recommendations"] == mock_response.content
    assert result["messages"][0] is mock_response
    assert result["current_step"] == "faq_done"


def test_baja_confianza_pasa_los_candidatos_como_contexto():
    """Los candidatos recuperados deben llegar al LLM dentro del mensaje de contexto."""
    from agents.faq_agent import FAQ_HIGH_CONFIDENCE_THRESHOLD

    faq = make_faq(FAQ_HIGH_CONFIDENCE_THRESHOLD - 0.20, answer="Reiniciar el Print Spooler.")

    with patch("agents.faq_agent.get_embedding", return_value=[0.0] * 1536), \
         patch("agents.faq_agent.search_faqs", return_value=[faq]), \
         patch("agents.faq_agent.llm") as mock_llm:

        mock_llm.invoke.return_value = AIMessage(content="respuesta")

        from agents.faq_agent import faq_agent
        faq_agent(make_state())

    mensajes_enviados = mock_llm.invoke.call_args[0][0]
    contexto = mensajes_enviados[-1].content
    assert "Reiniciar el Print Spooler." in contexto


# ---------------------------------------------------------------------------
# Prueba de manejo de errores
# ---------------------------------------------------------------------------

def test_raises_value_error_on_search_failure():
    """Un fallo en la búsqueda debe convertirse en ValueError con mensaje descriptivo."""
    with patch("agents.faq_agent.get_embedding", return_value=[0.0] * 1536), \
         patch("agents.faq_agent.search_faqs", side_effect=Exception("DB connection failed")):

        from agents.faq_agent import faq_agent
        with pytest.raises(ValueError, match="Ocurrió un error en el agente de FAQs"):
            faq_agent(make_state())
