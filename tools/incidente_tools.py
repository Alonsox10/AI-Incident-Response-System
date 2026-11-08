from database.db import get_pool
from langchain_core.tools import tool
from loguru import logger
import time


@tool
async def search_incident_by_category(category: str):
    """Busca incidentes en la base de datos por categoría y devuelve hasta 5 resultados."""
    try:
        logger.info(f"[DB] Buscando incidentes por categoria | categoria={category}")
        pool = await get_pool()

        query = """
        SELECT title, priority
        FROM incidents
        WHERE category = %s
        LIMIT 5
        """

        async with pool.connection() as conexion:
            cur = await conexion.execute(query, (category,))
            result = await cur.fetchall()

        logger.info(f"[DB] Incidentes encontrados por categoria | total={len(result)}")
        return [{"title": row[0], "priority": row[1]} for row in result]

    except Exception as e:
        logger.error(f"Error al buscar incidentes por categoría: {e}")
        raise ValueError("Ocurrió un error al buscar incidentes por categoría.")


@tool
async def insert_incident(title: str, category: str, priority: str):
    """Inserta un nuevo incidente en la base de datos."""
    try:
        logger.info(f"[DB] Registrando incidente | titulo='{title[:60]}' | categoria={category} | prioridad={priority}")
        inicio = time.perf_counter()
        pool = await get_pool()

        query = """
        INSERT INTO incidents (title, category, priority)
        VALUES (%s, %s, %s)
        """

        # El pool abre las conexiones con autocommit, así que no hace falta commit explícito.
        async with pool.connection() as conexion:
            await conexion.execute(query, (title, category, priority))

        duracion = time.perf_counter() - inicio
        logger.info(f"[DB] Incidente registrado correctamente | tiempo={duracion:.2f}s")
        return {"status": "success", "message": "Incidente registrado correctamente"}

    except Exception as e:
        # Esta tool devuelve el error en vez de relanzarlo: su resultado vuelve al LLM,
        # y un fallo de registro no debe tumbar el diagnóstico que ya se está armando.
        logger.error(f"Error al insertar incidente: {e}")
        return {"status": "error", "message": str(e)}
