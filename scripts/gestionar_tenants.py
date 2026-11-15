"""
Alta, listado, rotación y baja de tenants.

Sin esto la autenticación de la Fase 2 no se puede operar: la base guarda solo el
SHA-256 de la clave, así que la clave en claro existe una única vez —en la salida de
este script— y no hay forma de recuperarla después.

Uso:
    python scripts/gestionar_tenants.py crear <nombre> [--admin]
    python scripts/gestionar_tenants.py listar
    python scripts/gestionar_tenants.py rotar <nombre>
    python scripts/gestionar_tenants.py desactivar <nombre>
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(override=True)

from database.db import cerrar_pool, get_pool
from service.auth import generar_api_key, hash_api_key

AVISO = (
    "\n  Guárdala ahora: solo se almacena su hash, así que esta es la única vez que se\n"
    "  puede leer. Si se pierde, se rota.\n"
)


async def crear(nombre: str, admin: bool) -> int:
    api_key = generar_api_key()
    rol = "admin" if admin else "user"
    pool = await get_pool()
    async with pool.connection() as conexion:
        try:
            cur = await conexion.execute(
                "INSERT INTO tenants (nombre, api_key_hash, rol) VALUES (%s, %s, %s) RETURNING id",
                (nombre, hash_api_key(api_key), rol),
            )
            (tenant_id,) = await cur.fetchone()
        except Exception as e:
            if "tenants_nombre_key" in str(e):
                print(f"Ya existe un tenant llamado '{nombre}'. Para darle una clave nueva: rotar.")
                return 1
            raise

    print(f"Tenant creado | id={tenant_id} | nombre={nombre} | rol={rol}")
    print(f"\n  X-API-Key: {api_key}")
    print(AVISO)
    return 0


async def listar() -> int:
    pool = await get_pool()
    async with pool.connection() as conexion:
        cur = await conexion.execute(
            "SELECT id, nombre, rol, activo, created_at FROM tenants ORDER BY id"
        )
        filas = await cur.fetchall()

    if not filas:
        print("No hay tenants. Crea uno con: python scripts/gestionar_tenants.py crear <nombre>")
        return 0

    print(f"{'id':>4}  {'nombre':<24} {'rol':<8} {'estado':<10} creado")
    for tenant_id, nombre, rol, activo, creado in filas:
        estado = "activo" if activo else "desactivado"
        print(f"{tenant_id:>4}  {nombre:<24} {rol:<8} {estado:<10} {creado:%Y-%m-%d %H:%M}")
    return 0


async def rotar(nombre: str) -> int:
    api_key = generar_api_key()
    pool = await get_pool()
    async with pool.connection() as conexion:
        cur = await conexion.execute(
            "UPDATE tenants SET api_key_hash = %s WHERE nombre = %s RETURNING id",
            (hash_api_key(api_key), nombre),
        )
        fila = await cur.fetchone()

    if fila is None:
        print(f"No existe el tenant '{nombre}'.")
        return 1

    print(f"Clave rotada para '{nombre}'. La anterior deja de funcionar de inmediato.")
    print(f"\n  X-API-Key: {api_key}")
    print(AVISO)
    return 0


async def desactivar(nombre: str) -> int:
    pool = await get_pool()
    async with pool.connection() as conexion:
        cur = await conexion.execute(
            "UPDATE tenants SET activo = FALSE WHERE nombre = %s RETURNING id",
            (nombre,),
        )
        fila = await cur.fetchone()

    if fila is None:
        print(f"No existe el tenant '{nombre}'.")
        return 1
    # Se desactiva en vez de borrar: los checkpoints de sus conversaciones siguen en la
    # base referenciando su id, y borrar la fila dejaría hilos sin dueño identificable.
    print(f"Tenant '{nombre}' desactivado. Sus peticiones pasan a devolver 401.")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description="Gestiona los tenants y sus API keys.")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_crear = sub.add_parser("crear", help="Crea un tenant y emite su API key.")
    p_crear.add_argument("nombre")
    p_crear.add_argument("--admin", action="store_true", help="Rol de administrador.")

    sub.add_parser("listar", help="Lista los tenants registrados.")

    p_rotar = sub.add_parser("rotar", help="Emite una clave nueva e invalida la anterior.")
    p_rotar.add_argument("nombre")

    p_baja = sub.add_parser("desactivar", help="Deja de aceptar la clave de un tenant.")
    p_baja.add_argument("nombre")

    args = parser.parse_args()

    try:
        if args.comando == "crear":
            return await crear(args.nombre, args.admin)
        if args.comando == "listar":
            return await listar()
        if args.comando == "rotar":
            return await rotar(args.nombre)
        return await desactivar(args.nombre)
    except Exception as e:
        print(f"Error: {e}")
        print("¿Aplicaste las migraciones? python scripts/migrate.py")
        return 1
    finally:
        await cerrar_pool()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
