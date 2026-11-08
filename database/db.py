"""
Pool asíncrono de PostgreSQL, compartido por todo el proceso.

Antes cada operación abría su propia conexión (`psycopg.connect` por llamada): un
incidente completo abría cuatro, pagando el handshake cada vez y consumiendo el
`max_connections` de la base bajo carga. Ahora hay un único pool.

El pool **no se crea al importar el módulo**, a propósito. Si se creara, el proceso
no arrancaría con la base caída y no habría forma de importar el grafo sin
infraestructura. Se abre de forma perezosa en el primer uso, y el `lifespan` de
FastAPI lo abre explícitamente al arrancar para fallar rápido y lo cierra al salir.
"""
import asyncio
import os
import sys

from dotenv import load_dotenv
from loguru import logger
from psycopg_pool import AsyncConnectionPool

# psycopg no puede trabajar en modo asíncrono sobre el ProactorEventLoop, que es el
# que asyncio usa por defecto en Windows: falla con InterfaceError al conectar. Se
# cambia la política acá porque este módulo es el primero que importa cualquier cosa
# que toque la base, así que queda fijada antes de que se cree ningún loop.
#
# Solo aplica al desarrollo local en Windows. En Docker/Linux —que es donde corre en
# producción— no se ejecuta y el comportamiento es el normal.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

load_dotenv(override=True)

DATABASE_URL = os.getenv("POSTGRES_URL")
if not DATABASE_URL:
    raise ValueError("La URL de la base de datos no está configurada en las variables de entorno.")

# Tope de conexiones por réplica. Con 20 caben varias réplicas dentro del
# max_connections=100 que Postgres trae por defecto.
POOL_MAX = int(os.getenv("POSTGRES_POOL_MAX", "20"))
POOL_MIN = int(os.getenv("POSTGRES_POOL_MIN", "2"))
# Sin esto, conectar a una base inalcanzable se queda esperando minutos.
CONNECT_TIMEOUT = int(os.getenv("POSTGRES_CONNECT_TIMEOUT", "10"))

_pool: AsyncConnectionPool | None = None


async def get_pool() -> AsyncConnectionPool:
    """
    Devuelve el pool, creándolo en el primer uso.

    Si un intento anterior falló, se descarta el pool muerto y se crea uno nuevo.
    Eso es justo lo que permite que el servicio se recupere solo cuando Postgres
    vuelve, en vez de quedar inutilizado hasta que alguien reinicie el contenedor.
    """
    global _pool

    # psycopg cierra el pool cuando `open()` agota el timeout. Conservar la
    # referencia a uno cerrado deja el proceso muerto para siempre: todas las
    # llamadas siguientes fallan con "the pool is already closed".
    if _pool is not None and _pool.closed:
        logger.warning("[DB] El pool estaba cerrado; se descarta y se reintenta")
        _pool = None

    if _pool is None:
        pool = AsyncConnectionPool(
            conninfo=DATABASE_URL,
            min_size=POOL_MIN,
            max_size=POOL_MAX,
            open=False,
            kwargs={"autocommit": True, "connect_timeout": CONNECT_TIMEOUT},
        )
        try:
            await pool.open(wait=True, timeout=CONNECT_TIMEOUT)
        except Exception:
            await pool.close()
            raise
        _pool = pool
        logger.info(f"[DB] Pool de conexiones abierto | min={POOL_MIN} max={POOL_MAX}")

    return _pool


async def cerrar_pool() -> None:
    """Cierra el pool. Lo llama el lifespan al apagar el servicio."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("[DB] Pool de conexiones cerrado")


def pool_abierto() -> bool:
    """Para el chequeo de readiness, sin forzar la creación del pool."""
    return _pool is not None
