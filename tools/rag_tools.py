import time
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
        logger.info(f"[RAG-KB] Buscando en base de conocimiento | query='{query[:80]}'")
        inicio = time.perf_counter()

        embedding = get_embedding(query)
        results = search_knowledge_base(embedding, top_k=4)

        duracion = time.perf_counter() - inicio

        if not results:
            logger.info(f"[RAG-KB] Sin resultados | tiempo={duracion:.2f}s")
            return "No se encontraron documentos relevantes en la base de conocimiento."

        max_sim = max(r["similarity"] for r in results)
        fuentes = list({r["source"] for r in results if r["source"]})
        logger.info(
            f"[RAG-KB] {len(results)} documentos encontrados | "
            f"similitud_max={max_sim:.0%} | fuentes={fuentes} | tiempo={duracion:.2f}s"
        )

        parts = []
        for i, r in enumerate(results, 1):
            source_label = f" [Fuente: {r['source']}]" if r["source"] else ""
            parts.append(
                f"[Documento {i} — similitud {r['similarity']:.0%}{source_label}]\n"
                f"{r['content']}"
            )
        return "\n\n---\n\n".join(parts)

    except Exception as e:
        logger.error(f"[RAG-KB] Error en la búsqueda: {e}")
        return "Error al consultar la base de conocimiento."


@tool
def search_similar_incidents_rag(incident_description: str) -> str:
    """
    Busca en la base de datos histórica de incidentes resueltos aquellos similares al actual
    usando similitud vectorial semántica. Úsala para descubrir cómo se diagnosticaron
    y resolvieron incidentes comparables en el pasado.
    """
    try:
        logger.info(f"[RAG-HIST] Buscando incidentes similares | query='{incident_description[:80]}'")
        inicio = time.perf_counter()

        embedding = get_embedding(incident_description)
        results = search_similar_incidents(embedding, top_k=3)

        duracion = time.perf_counter() - inicio

        if not results:
            logger.info(f"[RAG-HIST] Sin resultados | tiempo={duracion:.2f}s")
            return "No se encontraron incidentes similares en el historial."

        max_sim = max(r["similarity"] for r in results)
        logger.info(
            f"[RAG-HIST] {len(results)} incidentes encontrados | "
            f"similitud_max={max_sim:.0%} | tiempo={duracion:.2f}s"
        )

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
        logger.error(f"[RAG-HIST] Error en la búsqueda: {e}")
        return "Error al buscar incidentes similares."
