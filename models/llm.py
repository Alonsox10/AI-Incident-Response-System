from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os


load_dotenv(override=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("La clave de API de OpenAI no está configurada en las variables de entorno.")

llm = ChatOpenAI(model="gpt-4", temperature=0)