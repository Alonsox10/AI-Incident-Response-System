import os

# Estas variables se setean ANTES de cualquier import de LangChain/OpenAI
# para que ChatOpenAI no falle al instanciarse sin credenciales reales.
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-real")
os.environ.setdefault("POSTGRES_URL", "postgresql://test:test@localhost:5432/test")

import pytest
from langchain_core.messages import HumanMessage


@pytest.fixture
def empty_state():
    """Estado inicial de un incidente sin clasificar."""
    return {
        "messages": [HumanMessage(content="El servidor de backend no responde")],
        "category": None,
        "priority": None,
        "possible_causes": [],
        "recommendations": [],
        "next_agent": None,
        "current_step": None,
    }


@pytest.fixture
def classified_state():
    """Estado después de que el clasificador procesó el incidente."""
    return {
        "messages": [HumanMessage(content="El servidor de backend no responde")],
        "category": "Error backend",
        "priority": "High",
        "possible_causes": ["Timeout de conexión", "Memoria agotada"],
        "recommendations": [],
        "next_agent": None,
        "current_step": "classifier_done",
    }
