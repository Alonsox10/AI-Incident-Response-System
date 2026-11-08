"""
Acceso a las tres tablas vectoriales de pgvector.

Todas las funciones son asíncronas y toman la conexión del pool de `database.db`.
El `async with pool.connection()` la devuelve al pool al salir, también si hay
excepción: por eso ya no hace falta el `try/finally` con `close()` que tenía
cada función cuando abría su propia conexión.
"""
import json
import os

from loguru import logger

from database.db import get_pool


def _vec(embedding: list[float]) -> str:
    """Convierte una lista de floats de Python al formato de cadena que pgvector espera: '[x1,x2,...]'."""
    return "[" + ",".join(str(x) for x in embedding) + "]"


async def initialize_vector_tables() -> None:
    """
    Ejecuta db/vector_schema.sql y db/faq_schema.sql para crear la extensión pgvector
    y las tablas knowledge_base, incident_embeddings y faqs (operación idempotente).

    Ya no se llama al importar el grafo: lo hace `scripts/migrate.py`, o el lifespan
    cuando se le pide explícitamente.
    """
    try:
        db_dir = os.path.join(os.path.dirname(__file__), "..", "db")
        sql = ""
        for schema_file in ("vector_schema.sql", "faq_schema.sql"):
            with open(os.path.join(db_dir, schema_file), "r", encoding="utf-8") as f:
                sql += f.read() + "\n"

        pool = await get_pool()
        async with pool.connection() as conexion:
            # Dividir por punto y coma y ejecutar cada sentencia por separado
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt:
                    await conexion.execute(stmt)

        logger.info("Tablas vectoriales inicializadas correctamente.")
    except Exception as e:
        logger.error(f"Error al inicializar las tablas vectoriales: {e}")
        raise


# ─── Base de Conocimiento ─────────────────────────────────────────────────────

async def store_document_chunk(
    content: str,
    embedding: list[float],
    source: str | None = None,
    chunk_index: int = 0,
    metadata: dict | None = None,
) -> int:
    """Inserta un fragmento de documento con su embedding en knowledge_base. Retorna el id de la fila creada."""
    try:
        pool = await get_pool()
        async with pool.connection() as conexion:
            cur = await conexion.execute(
                """
                INSERT INTO knowledge_base (content, source, chunk_index, embedding, metadata)
                VALUES (%s, %s, %s, %s::vector, %s::jsonb)
                RETURNING id
                """,
                (content, source, chunk_index, _vec(embedding), json.dumps(metadata or {})),
            )
            row = await cur.fetchone()
        return row[0]
    except Exception as e:
        logger.error(f"Error al almacenar el fragmento del documento: {e}")
        raise


async def search_knowledge_base(
    query_embedding: list[float],
    top_k: int = 5,
    similarity_threshold: float = 0.40,
) -> list[dict]:
    """
    Retorna hasta top_k fragmentos de la base de conocimiento cuya similitud coseno con
    query_embedding sea >= similarity_threshold, ordenados de mayor a menor similitud.
    """
    try:
        pool = await get_pool()
        vec = _vec(query_embedding)
        async with pool.connection() as conexion:
            cur = await conexion.execute(
                """
                SELECT id, content, source, chunk_index, metadata,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM knowledge_base
                WHERE 1 - (embedding <=> %s::vector) >= %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vec, vec, similarity_threshold, vec, top_k),
            )
            rows = await cur.fetchall()

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


# ─── Embeddings de Incidentes ─────────────────────────────────────────────────

async def store_incident_embedding(
    description: str,
    category: str,
    priority: str,
    resolution: str,
    embedding: list[float],
) -> int:
    """Persiste un incidente resuelto con su embedding para recuperación RAG futura."""
    try:
        pool = await get_pool()
        async with pool.connection() as conexion:
            cur = await conexion.execute(
                """
                INSERT INTO incident_embeddings (description, category, priority, resolution, embedding)
                VALUES (%s, %s, %s, %s, %s::vector)
                RETURNING id
                """,
                (description, category, priority, resolution, _vec(embedding)),
            )
            row = await cur.fetchone()
        return row[0]
    except Exception as e:
        logger.error(f"Error al almacenar el embedding del incidente: {e}")
        raise


async def search_similar_incidents(
    query_embedding: list[float],
    top_k: int = 3,
    similarity_threshold: float = 0.40,
) -> list[dict]:
    """
    Retorna hasta top_k incidentes históricos resueltos cuya similitud coseno con
    query_embedding sea >= similarity_threshold, ordenados de mayor a menor similitud.
    """
    try:
        pool = await get_pool()
        vec = _vec(query_embedding)
        async with pool.connection() as conexion:
            cur = await conexion.execute(
                """
                SELECT id, description, category, priority, resolution,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM incident_embeddings
                WHERE 1 - (embedding <=> %s::vector) >= %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vec, vec, similarity_threshold, vec, top_k),
            )
            rows = await cur.fetchall()

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


# ─── FAQs ─────────────────────────────────────────────────────────────────────

async def store_faq(
    question: str,
    answer: str,
    category: str,
    embedding: list[float],
    metadata: dict | None = None,
) -> int:
    """Persiste una FAQ con el embedding de su pregunta. Retorna el id de la fila creada."""
    try:
        pool = await get_pool()
        async with pool.connection() as conexion:
            cur = await conexion.execute(
                """
                INSERT INTO faqs (question, answer, category, embedding, metadata)
                VALUES (%s, %s, %s, %s::vector, %s::jsonb)
                RETURNING id
                """,
                (question, answer, category, _vec(embedding), json.dumps(metadata or {})),
            )
            row = await cur.fetchone()
        return row[0]
    except Exception as e:
        logger.error(f"Error al almacenar la FAQ: {e}")
        raise


async def search_faqs(
    query_embedding: list[float],
    top_k: int = 3,
    similarity_threshold: float = 0.40,
) -> list[dict]:
    """
    Retorna hasta top_k FAQs cuya similitud coseno con query_embedding sea
    >= similarity_threshold, ordenadas de mayor a menor similitud.
    """
    try:
        pool = await get_pool()
        vec = _vec(query_embedding)
        async with pool.connection() as conexion:
            cur = await conexion.execute(
                """
                SELECT id, question, answer, category, metadata,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM faqs
                WHERE 1 - (embedding <=> %s::vector) >= %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (vec, vec, similarity_threshold, vec, top_k),
            )
            rows = await cur.fetchall()

        return [
            {
                "id": row[0],
                "question": row[1],
                "answer": row[2],
                "category": row[3],
                "metadata": row[4],
                "similarity": float(row[5]),
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"Error al buscar en las FAQs: {e}")
        raise
