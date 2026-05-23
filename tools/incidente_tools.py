from database.db import get_connection
from langchain_core.tools import tool
from loguru import logger


@tool
def search_incident_by_category(category: str):
    """Busca incidentes en la base de datos por categoría y devuelve hasta 5 resultados."""
    connection = None
    try:
        connection = get_connection()

        query = """
        SELECT title, priority
        FROM incidents
        WHERE category = %s
        LIMIT 5
        """

        result = connection.execute(query, (category,)).fetchall()

        return [{"title": row[0], "priority": row[1]} for row in result]
    
    except Exception as e:
        logger.error(f"Error al buscar incidentes por categoría: {e}")
        raise ValueError("Ocurrió un error al buscar incidentes por categoría.")
    
    finally:
        if connection:
            connection.close()


@tool
def insert_incident(title: str, category: str, priority: str):
    """Inserta un nuevo incidente en la base de datos."""

    connection = None

    try:
        connection = get_connection()

        query = """
        INSERT INTO incidents (title, category, priority)
        VALUES (%s, %s, %s)
        """

        connection.execute(query, (title, category, priority))

        connection.commit()

        return {
            "status": "success",
            "message": "Incidente registrado correctamente"
        }

    except Exception as e:
        logger.error(f"Error al insertar incidente: {e}")

        return {
            "status": "error",
            "message": str(e)
        }

    finally:
        if connection:
            connection.close()

    
