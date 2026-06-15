"""
Tests unitarios para el agente clasificador.

El classifier recibe el mensaje del usuario y devuelve categoría, prioridad
y causas posibles usando un LLM con salida estructurada.
Parcheamos `llm_structured` (variable de módulo) para no llamar a la API real.
"""
import pytest
from unittest.mock import patch
from langchain_core.messages import HumanMessage
from schemas.models import IncidentClassificationOutput


def make_state(user_input="La base de datos no responde"):
    return {
        "messages": [HumanMessage(content=user_input)],
    }


# ---------------------------------------------------------------------------
# Pruebas de clasificación por categoría
# ---------------------------------------------------------------------------

def test_classifies_backend_incident():
    """Incidente de base de datos debe clasificarse como Error backend."""
    with patch("agents.classifier_agent.llm_structured") as mock:
        mock.invoke.return_value = IncidentClassificationOutput(
            category="Error backend",
            priority="High",
            possible_causes=["Timeout de conexión", "Memoria agotada"],
        )

        from agents.classifier_agent import classifier_agent
        result = classifier_agent(make_state())

    assert result["category"] == "Error backend"
    assert result["priority"] == "High"
    assert result["current_step"] == "classifier_done"


def test_classifies_security_incident():
    """Acceso no autorizado debe clasificarse como Seguridad."""
    with patch("agents.classifier_agent.llm_structured") as mock:
        mock.invoke.return_value = IncidentClassificationOutput(
            category="Seguridad",
            priority="High",
            possible_causes=["Acceso no autorizado", "Brute force attack"],
        )

        from agents.classifier_agent import classifier_agent
        result = classifier_agent(make_state("Detectamos acceso no autorizado al sistema"))

    assert result["category"] == "Seguridad"
    assert result["priority"] == "High"
    assert result["current_step"] == "classifier_done"


def test_classifies_infrastructure_incident():
    """Servidor lento debe clasificarse como Infraestructura con prioridad media."""
    with patch("agents.classifier_agent.llm_structured") as mock:
        mock.invoke.return_value = IncidentClassificationOutput(
            category="Infraestructura",
            priority="Medium",
            possible_causes=["Disco lleno", "RAM agotada", "CPU al 100%"],
        )

        from agents.classifier_agent import classifier_agent
        result = classifier_agent(make_state("El servidor está muy lento"))

    assert result["category"] == "Infraestructura"
    assert result["priority"] == "Medium"


# ---------------------------------------------------------------------------
# Pruebas de estructura de respuesta
# ---------------------------------------------------------------------------

def test_returns_list_of_possible_causes():
    """possible_causes debe ser una lista."""
    with patch("agents.classifier_agent.llm_structured") as mock:
        mock.invoke.return_value = IncidentClassificationOutput(
            category="Infraestructura",
            priority="Medium",
            possible_causes=["Disco lleno", "RAM agotada", "CPU al 100%"],
        )

        from agents.classifier_agent import classifier_agent
        result = classifier_agent(make_state())

    assert isinstance(result["possible_causes"], list)
    assert len(result["possible_causes"]) == 3


def test_always_sets_current_step_to_classifier_done():
    """current_step siempre debe ser 'classifier_done' al finalizar."""
    with patch("agents.classifier_agent.llm_structured") as mock:
        mock.invoke.return_value = IncidentClassificationOutput(
            category="Redes",
            priority="Low",
            possible_causes=["DNS mal configurado"],
        )

        from agents.classifier_agent import classifier_agent
        result = classifier_agent(make_state())

    assert result["current_step"] == "classifier_done"


def test_returns_all_required_keys():
    """El resultado debe contener category, priority, possible_causes y current_step."""
    with patch("agents.classifier_agent.llm_structured") as mock:
        mock.invoke.return_value = IncidentClassificationOutput(
            category="Error frontend",
            priority="Low",
            possible_causes=["CSS roto"],
        )

        from agents.classifier_agent import classifier_agent
        result = classifier_agent(make_state())

    assert all(k in result for k in ["category", "priority", "possible_causes", "current_step"])


# ---------------------------------------------------------------------------
# Prueba de manejo de errores
# ---------------------------------------------------------------------------

def test_raises_value_error_on_llm_failure():
    """Un fallo del LLM debe convertirse en ValueError con mensaje descriptivo."""
    with patch("agents.classifier_agent.llm_structured") as mock:
        mock.invoke.side_effect = Exception("API timeout")

        from agents.classifier_agent import classifier_agent
        with pytest.raises(ValueError, match="Ocurrió un error en el agente clasificador"):
            classifier_agent(make_state())
