from langchain_openai import OpenAIEmbeddings
from loguru import logger
from dotenv import load_dotenv
import os

load_dotenv(override=True)

# Mismo criterio que en models/llm.py: sin timeout explícito se hereda el del SDK,
# que ronda los 10 minutos. Los embeddings son más rápidos que una generación, pero
# la ingesta en lote puede pedir cientos de fragmentos en una sola llamada, así que
# el margen se mantiene igual de holgado.
EMBEDDINGS_TIMEOUT = float(os.getenv("EMBEDDINGS_TIMEOUT", "30"))
EMBEDDINGS_MAX_RETRIES = int(os.getenv("EMBEDDINGS_MAX_RETRIES", "3"))

# text-embedding-3-small: 1536 dimensiones, económico y preciso
_embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small",
    timeout=EMBEDDINGS_TIMEOUT,
    max_retries=EMBEDDINGS_MAX_RETRIES,
)


async def get_embedding(text: str) -> list[float]:
    """Genera un embedding vectorial para el texto dado."""
    try:
        return await _embeddings.aembed_query(text.replace("\n", " ").strip())
    except Exception as e:
        logger.error(f"Error al generar el embedding: {e}")
        raise


async def get_embeddings_lote(textos: list[str]) -> list[list[float]]:
    """
    Vectoriza varios textos en una sola llamada.

    La ingesta de PDF hacía una llamada por fragmento, en serie. Para un manual de
    100 páginas eso son cientos de viajes de ida y vuelta; en lote es uno por tanda.
    """
    try:
        limpios = [t.replace("\n", " ").strip() for t in textos]
        return await _embeddings.aembed_documents(limpios)
    except Exception as e:
        logger.error(f"Error al generar los embeddings en lote: {e}")
        raise


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> list[str]:
    """Divide el texto en fragmentos solapados basados en palabras para su embedding."""
    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    chunks = []
    step = chunk_size - overlap
    for i in range(0, len(words), step):
        chunk = " ".join(words[i : i + chunk_size])
        chunks.append(chunk)
        if i + chunk_size >= len(words):
            break
    return chunks
