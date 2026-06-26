from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from tools.incidente_tools import search_incident_by_category, insert_incident
from tools.rag_tools import search_knowledge_base_rag, search_similar_incidents_rag
import os


load_dotenv(override=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("La clave de API de OpenAI no está configurada en las variables de entorno.")

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# Todas las herramientas disponibles para el agente de recomendación (existentes + RAG)
llm_bind_tools = llm.bind_tools([
    search_incident_by_category,
    insert_incident,
    search_knowledge_base_rag,
    search_similar_incidents_rag,
])
