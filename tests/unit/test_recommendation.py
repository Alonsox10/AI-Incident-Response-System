"""
Tests unitarios para el agente de recomendaciones.

El recommendation agent usa `llm_bind_tools` (LLM con tools enlazadas) y
devuelve el contenido de la respuesta como recomendaciones.
Parcheamos `llm_bind_tools` importado en el módulo del agente.
"""
import pytest
from unittest.mock import patch
from langchain_core.messages import HumanMessage, AIMessage


def make_state(user_input="El servidor está caído", category="Error backend", priority="High"):
    return {
        "messages": [HumanMessage(content=user_input)],
        "category": category,
        "priority": priority,
    }


# ---------------------------------------------------------------------------
# Pruebas de estructura de respuesta
# ---------------------------------------------------------------------------

def test_returns_messages_and_recommendations():
    """El resultado debe contener 'messages', 'recommendations' y 'current_step'."""
    mock_response = AIMessage(content="Reiniciar el servicio de backend y verificar los logs")

    with patch("agents.recomendation_agent.llm_bind_tools") as mock_llm:
        mock_llm.invoke.return_value = mock_response

        from agents.recomendation_agent import recomendation_agent
        result = recomendation_agent(make_state())

    assert "messages" in result
    assert "recommendations" in result
    assert "current_step" in result


def test_recommendations_content_matches_llm_response():
    """recommendations debe ser exactamente el contenido del mensaje del LLM."""
    expected = "1. Revisar logs\n2. Reiniciar el servicio\n3. Verificar conexión DB"
    mock_response = AIMessage(content=expected)

    with patch("agents.recomendation_agent.llm_bind_tools") as mock_llm:
        mock_llm.invoke.return_value = mock_response

        from agents.recomendation_agent import recomendation_agent
        result = recomendation_agent(make_state())

    assert result["recommendations"] == expected


def test_sets_current_step_to_recommendation_done():
    """current_step debe quedar como 'recommendation_done'."""
    with patch("agents.recomendation_agent.llm_bind_tools") as mock_llm:
        mock_llm.invoke.return_value = AIMessage(content="Alguna recomendación")

        from agents.recomendation_agent import recomendation_agent
        result = recomendation_agent(make_state())

    assert result["current_step"] == "recommendation_done"


def test_messages_list_contains_llm_response():
    """La lista 'messages' debe contener exactamente el AIMessage devuelto por el LLM."""
    mock_response = AIMessage(content="Recomendaciones técnicas")

    with patch("agents.recomendation_agent.llm_bind_tools") as mock_llm:
        mock_llm.invoke.return_value = mock_response

        from agents.recomendation_agent import recomendation_agent
        result = recomendation_agent(make_state())

    assert isinstance(result["messages"], list)
    assert len(result["messages"]) == 1
    assert result["messages"][0] is mock_response


def test_uses_category_and_priority_from_state():
    """El agente debe invocar el LLM (una vez) con el contexto del estado."""
    with patch("agents.recomendation_agent.llm_bind_tools") as mock_llm:
        mock_llm.invoke.return_value = AIMessage(content="recomendación")

        from agents.recomendation_agent import recomendation_agent
        recomendation_agent(make_state(category="Seguridad", priority="High"))

    mock_llm.invoke.assert_called_once()


# ---------------------------------------------------------------------------
# Prueba de manejo de errores
# ---------------------------------------------------------------------------

def test_raises_value_error_on_llm_failure():
    """Un fallo del LLM debe convertirse en ValueError con mensaje descriptivo."""
    with patch("agents.recomendation_agent.llm_bind_tools") as mock_llm:
        mock_llm.invoke.side_effect = Exception("API connection failed")

        from agents.recomendation_agent import recomendation_agent
        with pytest.raises(ValueError, match="Ocurrió un error en el agente de recomendación"):
            recomendation_agent(make_state())
