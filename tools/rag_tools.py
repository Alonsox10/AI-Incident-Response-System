from langchain_core.tools import tool
from loguru import logger

from service.embedding_service import get_embedding
from database.vector_db import search_knowledge_base, search_similar_incidents


@tool
def search_knowledge_base_rag(query: str) -> str:
    """
    Busca en la base de conocimiento usando similitud vectorial semántica para encontrar
    documentación técnica, runbooks o guías de procedimientos relevantes al incidente.
    Úsala cuando necesites material de referencia externo.
    """
    try:
        embedding = get_embedding(query)
        results = search_knowledge_base(embedding, top_k=4)

        if not results:
            return "No se encontraron documentos relevantes en la base de conocimiento."

        parts = []
        for i, r in enumerate(results, 1):
            source_label = f" [Fuente: {r['source']}]" if r["source"] else ""
            parts.append(
                f"[Documento {i} — similitud {r['similarity']:.0%}{source_label}]\n"
                f"{r['content']}"
            )
        return "\n\n---\n\n".join(parts)

    except Exception as e:
        logger.error(f"Error en la búsqueda RAG de la base de conocimiento: {e}")
        return "Error al consultar la base de conocimiento."


@tool
def search_similar_incidents_rag(incident_description: str) -> str:
    """
    Busca en la base de datos histórica de incidentes resueltos aquellos similares al actual
    usando similitud vectorial semántica. Úsala para descubrir cómo se diagnosticaron
    y resolvieron incidentes comparables en el pasado.
    """
    try:
        embedding = get_embedding(incident_description)
        results = search_similar_incidents(embedding, top_k=3)

        if not results:
            return "No se encontraron incidentes similares en el historial."

        parts = []
        for i, r in enumerate(results, 1):
            parts.append(
                f"[Incidente histórico {i} — similitud {r['similarity']:.0%}]\n"
                f"Descripción: {r['description']}\n"
                f"Categoría: {r['category']} | Prioridad: {r['priority']}\n"
                f"Resolución aplicada: {r['resolution']}"
            )
        return "\n\n---\n\n".join(parts)

    except Exception as e:
        logger.error(f"Error en la búsqueda RAG de incidentes: {e}")
        return "Error al buscar incidentes similares."
