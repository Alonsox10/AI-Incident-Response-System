from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from tools.incidente_tools import search_incident_by_category, insert_incident
import os


load_dotenv(override=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("La clave de API de OpenAI no está configurada en las variables de entorno.")

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

llm_bind_tools = llm.bind_tools([search_incident_by_category, insert_incident])
