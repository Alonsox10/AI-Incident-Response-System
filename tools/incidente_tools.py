from database.db import get_connection
from langchain_core.tools import tool
from loguru import logger


@tool
def search_incident_by_category(category: str):
    try:

        connection = get_connection()
        cursor = connection.cursor()

        query = """
        SELECT title, priority
        FROM incidents
        WHERE category = %s
        LIMIT 5
        """

        cursor.execute(query, (category,))
        result = cursor.fetchall()
        connection.close()
        cursor.close()

        # Transformar el resultado en una lista de diccionarios
        return [{"title": row[0], "priority": row[1]} for row in result]
    
    except Exception as e:
        logger.error(f"Error al buscar incidentes por categoría: {e}")
        raise ValueError("Ocurrió un error al buscar incidentes por categoría.")

    
