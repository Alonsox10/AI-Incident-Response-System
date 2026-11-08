from langchain_openai import OpenAIEmbeddings
from loguru import logger
from dotenv import load_dotenv

load_dotenv(override=True)

# text-embedding-3-small: 1536 dimensiones, económico y preciso
_embeddings = OpenAIEmbeddings(model="text-embedding-3-small")


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
