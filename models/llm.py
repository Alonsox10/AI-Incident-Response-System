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

# Sin estos dos valores se heredan los defaults del SDK, cuyo timeout de request ronda
# los 10 minutos: un cuelgue de la API dejaba una corrutina ocupada todo ese rato y el
# fallo no aparecía como error en ninguna parte. 30 s es holgado —el clasificador
# promedia 1,5 s— y convierte un cuelgue en un error rápido y visible.
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "30"))

# El backoff exponencial con jitter lo implementa el propio SDK de OpenAI entre
# reintentos; acá solo se fija cuántos. No hace falta una política propia.
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))


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


llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0,
    timeout=LLM_TIMEOUT,
    max_retries=LLM_MAX_RETRIES,
    callbacks=[ContadorDeTokens()],
)

# Todas las herramientas disponibles para el agente de recomendación (existentes + RAG)
llm_bind_tools = llm.bind_tools([
    search_incident_by_category,
    insert_incident,
    search_knowledge_base_rag,
    search_similar_incidents_rag,
])
