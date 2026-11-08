"""
Aplica el esquema de base de datos. Paso previo al arranque, nunca desde el runtime.

Antes el DDL se ejecutaba al importar `graphs/incidente_graph.py`: cada réplica lo
lanzaba al arrancar, en cada despliegue, incluido el `CREATE INDEX` HNSW, que sobre
una tabla poblada es costoso y bloqueante. Ahora se corre una vez, de forma explícita
y auditable.

Uso:
    python scripts/migrate.py            # aplica todo lo pendiente
    python scripts/migrate.py --estado   # solo muestra qué se aplicó y qué falta

Las migraciones son los `.sql` de `db/`, en orden alfabético. Cada una se registra en
la tabla `schema_migrations`, así que volver a correr el script no reaplica nada.
Es idempotente por partida doble: por el registro y porque los `.sql` usan
`IF NOT EXISTS`.
"""
import argparse
import asyncio
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)

from database.db import cerrar_pool, get_pool

DIR_MIGRACIONES = Path(__file__).parent.parent / "db"

# `queris.sql` es un archivo de apuntes, no una migración: ningún código lo ejecuta.
EXCLUIDOS = {"queris.sql"}

TABLA_REGISTRO = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    nombre      TEXT PRIMARY KEY,
    hash        TEXT NOT NULL,
    aplicada_en TIMESTAMP DEFAULT NOW()
)
"""


def _migraciones() -> list[Path]:
    return sorted(p for p in DIR_MIGRACIONES.glob("*.sql") if p.name not in EXCLUIDOS)


async def _aplicadas(conexion) -> dict[str, str]:
    cur = await conexion.execute("SELECT nombre, hash FROM schema_migrations")
    return {nombre: h for nombre, h in await cur.fetchall()}


async def main() -> int:
    parser = argparse.ArgumentParser(description="Aplica el esquema de base de datos.")
    parser.add_argument("--estado", action="store_true", help="Solo informar, sin aplicar nada.")
    args = parser.parse_args()

    pool = await get_pool()
    try:
        async with pool.connection() as conexion:
            await conexion.execute(TABLA_REGISTRO)
            ya = await _aplicadas(conexion)

            pendientes, modificadas = [], []
            for archivo in _migraciones():
                sql = archivo.read_text(encoding="utf-8")
                h = hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16]
                if archivo.name not in ya:
                    pendientes.append((archivo, sql, h))
                elif ya[archivo.name] != h:
                    modificadas.append(archivo.name)

            for nombre in modificadas:
                # No se reaplica sola: reejecutar un .sql editado puede ser destructivo.
                print(f"  [aviso] '{nombre}' cambió desde que se aplicó. Revisar a mano.")

            if args.estado:
                print(f"\naplicadas: {len(ya)} | pendientes: {len(pendientes)}")
                for archivo, _, _ in pendientes:
                    print(f"  pendiente: {archivo.name}")
                return 0

            if not pendientes:
                print("Sin migraciones pendientes.")
                return 0

            for archivo, sql, h in pendientes:
                print(f"  aplicando {archivo.name}...")
                for stmt in sql.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        await conexion.execute(stmt)
                await conexion.execute(
                    "INSERT INTO schema_migrations (nombre, hash) VALUES (%s, %s)",
                    (archivo.name, h),
                )
                print(f"  [ok] {archivo.name}")

            print(f"\n{len(pendientes)} migracion(es) aplicada(s).")
        return 0
    finally:
        await cerrar_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
