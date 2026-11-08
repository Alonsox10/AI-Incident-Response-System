"""
Entrypoint del servidor.

Existe por una incompatibilidad concreta en Windows: psycopg no puede trabajar en
modo asíncrono sobre el `ProactorEventLoop`, y uvicorn lo impone en win32 pasándolo
como `loop_factory` —lo que ignora cualquier `set_event_loop_policy`—. Sin esto, el
pool no abre y el servicio arranca degradado con `/ready` en 503.

En Linux, que es donde corre en producción (Docker), no cambia nada: usa el loop
por defecto y `uvicorn main:app` sigue siendo igual de válido allí.

Uso:
    python run.py                      # local
    python run.py --reload             # con recarga automática
    uvicorn main:app --host 0.0.0.0    # válido en Linux, NO en Windows
"""
import argparse
import asyncio
import os
import sys

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Arranca la API de respuesta a incidentes.")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--workers", type=int, default=int(os.getenv("WEB_CONCURRENCY", "1")))
    args = parser.parse_args()

    # --reload y --workers necesitan el gestor de procesos de uvicorn, que arranca
    # cada worker por su cuenta: ahí no se puede imponer el loop desde acá.
    if args.reload or args.workers > 1:
        if sys.platform == "win32":
            print(
                "AVISO: en Windows, --reload y --workers usan el ProactorEventLoop y el "
                "pool asíncrono de Postgres no abrirá. Para desarrollo local usa "
                "`python run.py` a secas.",
                file=sys.stderr,
            )
        uvicorn.run("main:app", host=args.host, port=args.port,
                    reload=args.reload, workers=None if args.reload else args.workers)
        return

    config = uvicorn.Config("main:app", host=args.host, port=args.port)
    server = uvicorn.Server(config)

    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            runner.run(server.serve())
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    main()
