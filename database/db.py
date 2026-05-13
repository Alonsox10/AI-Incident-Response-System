import asyncpg
from dotenv import load_dotenv
import os
from loguru import logger
import asyncio



load_dotenv(override=True)

DATABASE_URL = os.getenv("POSTGRES_URL")
if not DATABASE_URL:
    raise ValueError("La URL de la base de datos no está configurada en las variables de entorno.")

async def get_connection():
    try:

        connection = await asyncpg.connect(DATABASE_URL)
        logger.info("Conexión a la base de datos establecida exitosamente.")
        return connection
    
    except Exception as e:
        logger.error(f"Error al conectar a la base de datos: {e}")
        raise
