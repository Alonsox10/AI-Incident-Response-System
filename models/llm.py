from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from tools.incidente_tools import search_incident_by_category, insert_incident
from tools.rag_tools import search_knowledge_base_rag, search_similar_incidents_rag
from service.observability import registrar_uso_tokens
import os


load_dotenv(override=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("La clave de API de OpenAI no está configurada en las variables de entorno.")


class ContadorDeTokens(BaseCallbackHandler):
    """
    Suma los tokens de cada llamada al LLM a las métricas.

    Se engancha acá y no en cada agente para que cuente todas las llamadas, incluidas
    las que haga un nodo futuro. El conteo sale del `usage` que devuelve el propio
    proveedor, así que es un dato medido y no una estimación.
    """

    def on_llm_end(self, response, **kwargs) -> None:
        uso = (response.llm_output or {}).get("token_usage") or {}
        entrada = uso.get("prompt_tokens")
        salida = uso.get("completion_tokens")
        if entrada is None and salida is None:
            # Algunos caminos devuelven el uso dentro de la generación, no en llm_output
            for grupo in response.generations:
                for gen in grupo:
                    meta = getattr(getattr(gen, "message", None), "usage_metadata", None) or {}
                    entrada = (entrada or 0) + meta.get("input_tokens", 0)
                    salida = (salida or 0) + meta.get("output_tokens", 0)
        registrar_uso_tokens(entrada or 0, salida or 0)


llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, callbacks=[ContadorDeTokens()])

# Todas las herramientas disponibles para el agente de recomendación (existentes + RAG)
llm_bind_tools = llm.bind_tools([
    search_incident_by_category,
    insert_incident,
    search_knowledge_base_rag,
    search_similar_incidents_rag,
])
