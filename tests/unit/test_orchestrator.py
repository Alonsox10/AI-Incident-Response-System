"""
Tests unitarios para el agente orquestador.

El orquestador analiza el estado actual del workflow y decide a qué agente
ir a continuación. Usamos `patch` para sustituir `llm_structured` (que ya
fue instanciado a nivel de módulo) por un Mock que devuelve valores fijos.
"""
import pytest
from unittest.mock import patch
from langchain_core.messages import HumanMessage
from schemas.models import OrquestatorOutput


def make_state(current_step=None, category=None, priority=None, recommendations=None):
    return {
        "messages": [HumanMessage(content="El servidor está caído")],
        "category": category,
        "priority": priority,
        "recommendations": recommendations,
        "current_step": current_step,
    }


# ---------------------------------------------------------------------------
# Pruebas de routing
# ---------------------------------------------------------------------------

def test_routes_to_classifier_when_no_step():
    """Sin current_step el orquestador debe enviar al classifier."""
    with patch("agents.orchestrator_agent.llm_structured") as mock:
        mock.invoke.return_value = OrquestatorOutput(next_agent="classifier")

        from agents.orchestrator_agent import orchestrator_agent
        result = orchestrator_agent(make_state(current_step=None))

    assert result["next_agent"] == "classifier"


def test_routes_to_recommendation_after_classifier():
    """Con current_step='classifier_done' debe enrutar a recommendation."""
    with patch("agents.orchestrator_agent.llm_structured") as mock:
        mock.invoke.return_value = OrquestatorOutput(next_agent="recommendation")

        from agents.orchestrator_agent import orchestrator_agent
        result = orchestrator_agent(make_state(current_step="classifier_done"))

    assert result["next_agent"] == "recommendation"


def test_routes_to_end_when_workflow_complete():
    """Con current_step='recommendation_done' debe enrutar a end."""
    with patch("agents.orchestrator_agent.llm_structured") as mock:
        mock.invoke.return_value = OrquestatorOutput(next_agent="end")

        from agents.orchestrator_agent import orchestrator_agent
        result = orchestrator_agent(make_state(current_step="recommendation_done"))

    assert result["next_agent"] == "end"


# ---------------------------------------------------------------------------
# Pruebas de estructura de respuesta
# ---------------------------------------------------------------------------

def test_response_contains_next_agent_key():
    """El resultado siempre debe tener la clave 'next_agent'."""
    with patch("agents.orchestrator_agent.llm_structured") as mock:
        mock.invoke.return_value = OrquestatorOutput(next_agent="classifier")

        from agents.orchestrator_agent import orchestrator_agent
        result = orchestrator_agent(make_state())

    assert "next_agent" in result


def test_llm_is_called_once_per_invocation():
    """El LLM debe ser invocado exactamente una vez por ejecución del agente."""
    with patch("agents.orchestrator_agent.llm_structured") as mock:
        mock.invoke.return_value = OrquestatorOutput(next_agent="classifier")

        from agents.orchestrator_agent import orchestrator_agent
        orchestrator_agent(make_state())

    mock.invoke.assert_called_once()


# ---------------------------------------------------------------------------
# Prueba de manejo de errores
# ---------------------------------------------------------------------------

def test_raises_value_error_on_llm_failure():
    """Un fallo del LLM debe convertirse en ValueError con mensaje descriptivo."""
    with patch("agents.orchestrator_agent.llm_structured") as mock:
        mock.invoke.side_effect = Exception("LLM connection failed")

        from agents.orchestrator_agent import orchestrator_agent
        with pytest.raises(ValueError, match="Ocurrió un error en el agente orquestador"):
            orchestrator_agent(make_state())
