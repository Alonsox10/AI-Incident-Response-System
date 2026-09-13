"""
Tests unitarios para el agente orquestador.

El orquestador analiza el estado actual del workflow y decide a qué agente
ir a continuación. Usamos `patch` para sustituir `llm_structured` (que ya
fue instanciado a nivel de módulo) por un Mock que devuelve valores fijos.

Antes de consultar al LLM, el orquestador hace un pre-chequeo determinístico contra
la tabla `faqs`. El fixture `sin_match_de_faq` lo neutraliza por defecto para que los
tests de routing por estado no dependan de la base ni de la API de embeddings; los
tests que ejercitan el pre-chequeo lo parchean explícitamente.
"""
import pytest
from unittest.mock import patch
from langchain_core.messages import HumanMessage
from schemas.models import OrquestatorOutput


@pytest.fixture(autouse=True)
def sin_match_de_faq():
    """Por defecto ninguna pregunta coincide con una FAQ documentada."""
    with patch("agents.orchestrator_agent._coincide_con_faq_documentada", return_value=None):
        yield


def make_state(
    current_step=None,
    category=None,
    priority=None,
    recommendations=None,
    user_input="El servidor está caído",
):
    return {
        "messages": [HumanMessage(content=user_input)],
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


def test_routes_to_faq_for_procedure_question():
    """Una pregunta general de procedimiento debe poder enrutar a faq."""
    with patch("agents.orchestrator_agent.llm_structured") as mock:
        mock.invoke.return_value = OrquestatorOutput(next_agent="faq")

        from agents.orchestrator_agent import orchestrator_agent
        result = orchestrator_agent(
            make_state(user_input="¿Cuál es el procedimiento ante un ransomware?")
        )

    assert result["next_agent"] == "faq"


def test_routes_to_end_after_faq():
    """Con current_step='faq_done' el workflow debe terminar."""
    with patch("agents.orchestrator_agent.llm_structured") as mock:
        mock.invoke.return_value = OrquestatorOutput(next_agent="end")

        from agents.orchestrator_agent import orchestrator_agent
        result = orchestrator_agent(make_state(current_step="faq_done"))

    assert result["next_agent"] == "end"


def test_faq_is_a_valid_orchestrator_output():
    """El schema del orquestador debe aceptar 'faq' como rama válida."""
    assert OrquestatorOutput(next_agent="faq").next_agent == "faq"


# ---------------------------------------------------------------------------
# Pre-chequeo determinístico contra la tabla faqs
# ---------------------------------------------------------------------------

def test_faq_documentada_enruta_a_faq_sin_consultar_al_llm():
    """Si la pregunta ya está documentada, se enruta a faq sin gastar una llamada al LLM."""
    with patch("agents.orchestrator_agent._coincide_con_faq_documentada", return_value=0.93), \
         patch("agents.orchestrator_agent.llm_structured") as mock:

        from agents.orchestrator_agent import orchestrator_agent
        result = orchestrator_agent(
            make_state(user_input="¿Por qué mi equipo tarda tanto en iniciar?")
        )

    assert result["next_agent"] == "faq"
    mock.invoke.assert_not_called()


def test_faq_documentada_gana_sobre_la_redaccion_de_sintoma_activo():
    """
    Un mensaje redactado como síntoma activo va a faq si coincide con una FAQ documentada.
    Es el comportamiento elegido: el match documentado pesa más que la redacción.
    """
    with patch("agents.orchestrator_agent._coincide_con_faq_documentada", return_value=0.88), \
         patch("agents.orchestrator_agent.llm_structured") as mock:
        mock.invoke.return_value = OrquestatorOutput(next_agent="classifier")

        from agents.orchestrator_agent import orchestrator_agent
        result = orchestrator_agent(
            make_state(user_input="Mi equipo no navega, tiene una IP 169.254.1.5")
        )

    assert result["next_agent"] == "faq"


def test_el_prechequeo_no_corre_con_el_workflow_ya_iniciado():
    """
    Con current_step ya definido el routing lo decide el estado, no el contenido:
    el pre-chequeo no debe secuestrar un workflow de incidente en curso.
    """
    mock_prechequeo_llamado = []

    def _espia(user_input):
        mock_prechequeo_llamado.append(user_input)
        return 0.99

    with patch("agents.orchestrator_agent._coincide_con_faq_documentada", side_effect=_espia), \
         patch("agents.orchestrator_agent.llm_structured") as mock:
        mock.invoke.return_value = OrquestatorOutput(next_agent="recommendation")

        from agents.orchestrator_agent import orchestrator_agent
        result = orchestrator_agent(make_state(current_step="classifier_done"))

    assert result["next_agent"] == "recommendation"
    assert mock_prechequeo_llamado == []


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
