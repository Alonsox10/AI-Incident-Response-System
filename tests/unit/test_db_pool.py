"""
Tests del pool asíncrono de Postgres.

Cubren la lógica de recuperación, que es un criterio de aceptación de la fase 1:
el servicio tiene que levantarse solo cuando la base vuelve, sin reiniciar el proceso.

Se testea con dobles en vez de contra una base real porque el comportamiento que
importa —qué hace el módulo cuando `open()` falla— es determinista y debe poder
verificarse en CI sin infraestructura.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import database.db as db


@pytest.fixture(autouse=True)
def _pool_limpio():
    """Cada test arranca sin pool: es estado global de módulo."""
    db._pool = None
    yield
    db._pool = None


def _pool_falso(cerrado=False):
    pool = MagicMock()
    pool.closed = cerrado
    pool.open = AsyncMock()
    pool.close = AsyncMock()
    return pool


async def test_crea_el_pool_en_el_primer_uso():
    pool = _pool_falso()
    with patch("database.db.AsyncConnectionPool", return_value=pool):
        obtenido = await db.get_pool()

    assert obtenido is pool
    pool.open.assert_awaited_once()


async def test_reutiliza_el_pool_en_llamadas_siguientes():
    """No debe abrir un pool nuevo por cada operación: ese era el problema B3."""
    pool = _pool_falso()
    with patch("database.db.AsyncConnectionPool", return_value=pool) as constructor:
        await db.get_pool()
        await db.get_pool()
        await db.get_pool()

    assert constructor.call_count == 1
    pool.open.assert_awaited_once()


async def test_un_open_fallido_no_deja_el_pool_registrado():
    """
    Si `open()` falla, psycopg cierra el pool. Guardarlo dejaría el proceso muerto
    para siempre: toda llamada posterior fallaría con "the pool is already closed".
    """
    pool = _pool_falso()
    pool.open.side_effect = Exception("no hay base")

    with patch("database.db.AsyncConnectionPool", return_value=pool):
        with pytest.raises(Exception, match="no hay base"):
            await db.get_pool()

    assert db._pool is None
    pool.close.assert_awaited_once()


async def test_se_recupera_cuando_la_base_vuelve():
    """El caso que importa: falla al arrancar y funciona en el reintento siguiente."""
    caido = _pool_falso()
    caido.open.side_effect = Exception("no hay base")
    sano = _pool_falso()

    with patch("database.db.AsyncConnectionPool", side_effect=[caido, sano]):
        with pytest.raises(Exception):
            await db.get_pool()       # la base está caída
        obtenido = await db.get_pool()  # la base volvió

    assert obtenido is sano
    assert db._pool is sano


async def test_descarta_un_pool_que_quedo_cerrado():
    """Aunque se haya abierto bien, si después aparece cerrado hay que reemplazarlo."""
    viejo = _pool_falso(cerrado=True)
    db._pool = viejo
    nuevo = _pool_falso()

    with patch("database.db.AsyncConnectionPool", return_value=nuevo):
        obtenido = await db.get_pool()

    assert obtenido is nuevo
    nuevo.open.assert_awaited_once()


async def test_pool_abierto_refleja_el_estado_sin_crear_nada():
    """El chequeo de readiness no debe provocar la creación del pool."""
    assert db.pool_abierto() is False
    db._pool = _pool_falso()
    assert db.pool_abierto() is True
