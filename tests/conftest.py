import os

# `database/db.py`, `models/llm.py` y `service/embedding_service.py` llaman
# `load_dotenv(override=True)` a nivel de import, lo que pisaría los valores dummy
# de abajo con las credenciales reales de `.env` (si existe) apenas se importe
# cualquier módulo de `agents/`, `models/` o `graphs/`. Neutralizamos `load_dotenv`
# ANTES de que eso ocurra para que la suite nunca dependa de red ni de Postgres real,
# aunque un test se olvide de mockear una llamada puntual al LLM o a la búsqueda vectorial.
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False

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
        "priority": "Alta",
        "possible_causes": ["Timeout de conexión", "Memoria agotada"],
        "recommendations": [],
        "next_agent": None,
        "current_step": "classifier_done",
    }
