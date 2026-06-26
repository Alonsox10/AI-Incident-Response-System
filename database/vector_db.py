import json
import os
from loguru import logger
from database.db import get_connection


def _vec(embedding: list[float]) -> str:
    """Convierte una lista de floats de Python al formato de cadena que pgvector espera: '[x1,x2,...]'."""
    return "[" + ",".join(str(x) for x in embedding) + "]"


def initialize_vector_tables() -> None:
    """
    Ejecuta db/vector_schema.sql para crear la extensión pgvector y las tablas
    knowledge_base e incident_embeddings (operación idempotente).
    """
    connection = None
    try:
        schema_path = os.path.join(os.path.dirname(__file__), "..", "db", "vector_schema.sql")
        with open(schema_path, "r", encoding="utf-8") as f:
            sql = f.read()

        connection = get_connection()
        # Dividir por punto y coma y ejecutar cada sentencia por separado
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt:
                connection.execute(stmt)

        logger.info("Tablas vectoriales inicializadas correctamente.")
    except Exception as e:
        logger.error(f"Error al inicializar las tablas vectoriales: {e}")
        raise
    finally:
        if connection:
            connection.close()


# ─── Base de Conocimiento ─────────────────────────────────────────────────────

def store_document_chunk(
    content: str,
    embedding: list[float],
    source: str | None = None,
    chunk_index: int = 0,
    metadata: dict | None = None,
) -> int:
    """Inserta un fragmento de documento con su embedding en knowledge_base. Retorna el id de la fila creada."""
    connection = None
    try:
        connection = get_connection()
        row = connection.execute(
            """
            INSERT INTO knowledge_base (content, source, chunk_index, embedding, metadata)
            VALUES (%s, %s, %s, %s::vector, %s::jsonb)
            RETURNING id
            """,
            (content, source, chunk_index, _vec(embedding), json.dumps(metadata or {})),
        ).fetchone()
        return row[0]
    except Exception as e:
        logger.error(f"Error al almacenar el fragmento del documento: {e}")
        raise
    finally:
        if connection:
            connection.close()


def search_knowledge_base(
    query_embedding: list[float],
    top_k: int = 5,
    similarity_threshold: float = 0.40,
) -> list[dict]:
    """
    Retorna hasta top_k fragmentos de la base de conocimiento cuya similitud coseno con
    query_embedding sea >= similarity_threshold, ordenados de mayor a menor similitud.
    """
    connection = None
    try:
        connection = get_connection()
        vec = _vec(query_embedding)
        rows = connection.execute(
            """
            SELECT id, content, source, chunk_index, metadata,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM knowledge_base
            WHERE 1 - (embedding <=> %s::vector) >= %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (vec, vec, similarity_threshold, vec, top_k),
        ).fetchall()

        return [
            {
                "id": row[0],
                "content": row[1],
                "source": row[2],
                "chunk_index": row[3],
                "metadata": row[4],
                "similarity": float(row[5]),
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"Error al buscar en la base de conocimiento: {e}")
        raise
    finally:
        if connection:
            connection.close()


# ─── Embeddings de Incidentes ─────────────────────────────────────────────────

def store_incident_embedding(
    description: str,
    category: str,
    priority: str,
    resolution: str,
    embedding: list[float],
) -> int:
    """Persiste un incidente resuelto con su embedding para recuperación RAG futura."""
    connection = None
    try:
        connection = get_connection()
        row = connection.execute(
            """
            INSERT INTO incident_embeddings (description, category, priority, resolution, embedding)
            VALUES (%s, %s, %s, %s, %s::vector)
            RETURNING id
            """,
            (description, category, priority, resolution, _vec(embedding)),
        ).fetchone()
        return row[0]
    except Exception as e:
        logger.error(f"Error al almacenar el embedding del incidente: {e}")
        raise
    finally:
        if connection:
            connection.close()


def search_similar_incidents(
    query_embedding: list[float],
    top_k: int = 3,
    similarity_threshold: float = 0.40,
) -> list[dict]:
    """
    Retorna hasta top_k incidentes históricos resueltos cuya similitud coseno con
    query_embedding sea >= similarity_threshold, ordenados de mayor a menor similitud.
    """
    connection = None
    try:
        connection = get_connection()
        vec = _vec(query_embedding)
        rows = connection.execute(
            """
            SELECT id, description, category, priority, resolution,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM incident_embeddings
            WHERE 1 - (embedding <=> %s::vector) >= %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (vec, vec, similarity_threshold, vec, top_k),
        ).fetchall()

        return [
            {
                "id": row[0],
                "description": row[1],
                "category": row[2],
                "priority": row[3],
                "resolution": row[4],
                "similarity": float(row[5]),
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"Error al buscar incidentes similares: {e}")
        raise
    finally:
        if connection:
            connection.close()
