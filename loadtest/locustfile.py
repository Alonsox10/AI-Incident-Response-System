"""
Prueba de carga sobre POST /incident.

Mide el techo de concurrencia real del servicio. La hipótesis a verificar es la de
B1 del plan de producción: como `handle_incident` es `def` y usa `invoke()`, FastAPI
lo manda al threadpool de AnyIO (40 hilos por defecto) y cada request ocupa un hilo
entero durante todo el workflow. Si es cierto, el throughput se aplana alrededor de
40 / (latencia media) sin importar cuántos usuarios más se agreguen.

Uso:
    # headless, rampa corta
    locust -f loadtest/locustfile.py --headless -u 20 -r 2 -t 3m \
           --host http://127.0.0.1:8000 --csv loadtest/resultados/run

    # con interfaz web para ver la rampa en vivo
    locust -f loadtest/locustfile.py --host http://127.0.0.1:8000

OJO CON EL COSTO: cada request dispara ~5-6 llamadas al LLM y ~3 de embeddings.
Una rampa larga con muchos usuarios se traduce en factura real. Empezar corto.

Variables:
    LOADTEST_SOLO_SALUD=1   solo golpea /health, sin gastar tokens. Sirve para
                            separar el techo del framework del costo del LLM.
    API_KEY=...             credencial del tenant. Obligatoria desde la Fase 2:
                            sin ella /incident responde 401 y la prueba mide
                            cuántos 401 por segundo aguanta el servicio, que no
                            es lo que interesa. Se emite con
                            `python scripts/gestionar_tenants.py crear carga`.
"""
import os
import random
import sys

from locust import HttpUser, between, task

SOLO_SALUD = os.getenv("LOADTEST_SOLO_SALUD", "").lower() in ("1", "true", "yes")
API_KEY = os.getenv("API_KEY", "")

if not SOLO_SALUD and not API_KEY:
    sys.exit(
        "Falta API_KEY. /incident exige autenticación desde la Fase 2, y una corrida "
        "sin credencial mediría 401 en vez del workflow.
"
        "  python scripts/gestionar_tenants.py crear carga"
    )

# Incidentes variados para que el clasificador no responda siempre lo mismo y para
# que el RAG tenga que recuperar de distintas zonas de la base.
INCIDENTES = [
    "El endpoint /api/v1/pagos devuelve error 500 en todas las peticiones tras el deploy.",
    "Se cayó el enlace de fibra de la sucursal norte y quedaron 40 personas sin servicio.",
    "Detectamos tráfico saliente anómalo hacia una IP desconocida desde facturación.",
    "El servidor de base de datos se quedó sin espacio en disco hace 10 minutos.",
    "Desde ayer no llega ningún correo externo, los mensajes quedan en cola.",
    "Las consultas a la base tardan más de 30 segundos y hay timeouts.",
    "La aplicación móvil crashea al abrir el módulo de reportes en Android 14.",
    "Los pods del servicio de órdenes están en CrashLoopBackOff desde hace 15 minutos.",
]


class UsuarioDeIncidentes(HttpUser):
    # Sin pausa artificial: queremos medir el techo del servicio, no simular
    # un ritmo humano. Con `between` el resultado diría más del wait que del sistema.
    wait_time = between(0, 0)

    @task
    def reportar_incidente(self):
        if SOLO_SALUD:
            self.client.get("/health", name="GET /health")
            return

        # Cada usuario virtual arranca sin cookie, así que cada request abre su
        # propia conversación en el checkpointer: no se contaminan entre sí.
        # Todos comparten el mismo tenant, que es justo lo que conviene medir: así
        # la prueba pega contra un único `thread_id` derivado por request y, de paso,
        # ejercita el límite por tenant si se baja RATE_LIMIT_INCIDENTES.
        self.client.post(
            "/incident",
            json={"user_input": random.choice(INCIDENTES)},
            headers={"X-API-Key": API_KEY},
            name="POST /incident",
            timeout=120,
        )
