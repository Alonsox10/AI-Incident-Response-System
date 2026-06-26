from langchain_openai import OpenAIEmbeddings
from loguru import logger
from dotenv import load_dotenv

load_dotenv(override=True)

# text-embedding-3-small: 1536 dimensiones, económico y preciso
_embeddings = OpenAIEmbeddings(model="text-embedding-3-small")


def get_embedding(text: str) -> list[float]:
    """Genera un embedding vectorial para el texto dado."""
    try:
        return _embeddings.embed_query(text.replace("\n", " ").strip())
    except Exception as e:
        logger.error(f"Error al generar el embedding: {e}")
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
