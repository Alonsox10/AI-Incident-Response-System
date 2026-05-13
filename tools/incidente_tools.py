from database.db import get_connection
from langchain_core.tools import tool
from loguru import logger


@tool
async def search_incident_by_category(category: str):
    """Busca incidentes en la base de datos por categoría y devuelve hasta 5 resultados."""
    connection = None
    try:
        connection = await get_connection()

        query = """
        SELECT title, priority
        FROM incidents
        WHERE category = $1
        LIMIT 5
        """

        result = await connection.fetch(query, category)

        return [{"title": row["title"], "priority": row["priority"]} for row in result]
    
    except Exception as e:
        logger.error(f"Error al buscar incidentes por categoría: {e}")
        raise ValueError("Ocurrió un error al buscar incidentes por categoría.")
    
    finally:
        if connection:
            await connection.close()


@tool
async def insert_incident(title: str, category: str, priority: str):
    """Inserta un nuevo incidente en la base de datos con título, categoría y prioridad."""
    connection = None
    try:
        connection = await get_connection()

        query = """
        INSERT INTO incidents (title, category, priority)
        VALUES ($1, $2, $3)
        """

        await connection.execute(query, title, category, priority)
    
    except Exception as e:
        logger.error(f"Error al insertar incidente: {e}")
        raise ValueError("Ocurrió un error al insertar el incidente.")
    
    finally:
        if connection:
            await connection.close()

    
