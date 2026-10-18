# Línea base de carga — antes de la Fase 1

Medición del estado **previo** a cualquier cambio de concurrencia. Es la cifra contra la
que se compara la Fase 1 del `PLAN_PRODUCCION.md`.

- **Fecha:** 2026-10-17
- **Commit:** `a23f2a8` + los cambios de instrumentación de la Fase 0 (sin tocar el grafo)
- **Entorno:** 1 worker de uvicorn, local, Windows. `gpt-4o-mini`, temperatura 0.
- **Herramienta:** Locust 2.46.7 — `loadtest/locustfile.py`
- **Endpoint:** `POST /incident`, 8 incidentes distintos rotados al azar, sin `wait_time`

> Es una medición local con un solo worker, no un entorno de pre-producción. Sirve como
> punto de comparación relativo (antes/después de la Fase 1), no como promesa de capacidad.

## Resultados

| Usuarios | Duración | Requests | Fallos | Throughput | p50 | p95 | Máx |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 90 s | 76 | **0 (0%)** | 0.87 req/s | 10.0 s | 13.0 s | 18.1 s |
| 50 | 90 s | 354 | **104 (29.4%)** | 3.94 req/s | 12.0 s | 17.0 s | 30.7 s |

Reproducir:

```bash
./venv/Scripts/python.exe -m locust -f loadtest/locustfile.py --headless \
  -u 10 -r 2 -t 90s --host http://127.0.0.1:8000 --csv loadtest/resultados/u10
```

## Punto de saturación

**Entre 10 y 50 usuarios concurrentes.** A 50 el servicio entrega 3.94 req/s y empieza a
fallar casi un tercio de las peticiones.

El throughput de 3.94 req/s coincide casi exactamente con la predicción de B1 en el plan
(~4 req/s por el techo de 40 hilos de AnyIO). **Pero la causa de los fallos es otra.**

## Hallazgo: el cuello de botella no es el que predecía el plan

Los 104 errores no son de base de datos ni de agotamiento de hilos. Son **429 de OpenAI**:

| Agente donde explota | Errores |
|---|---:|
| Recomendación | 136 |
| Clasificador | 8 |
| Orquestador | 1 |

```
Error en el agente de recomendación: Error code: 429 -
{'error': {'message': 'Rate limit reached for gpt-4o-mini ...'}}
```

Tres consecuencias para el plan:

1. **El límite real de hoy es la cuota de la API, no la concurrencia del proceso.** Se
   alcanza *antes* que el techo de los 40 hilos. Pasar todo a async (Fase 1) sube el
   número de requests en vuelo, pero si la cuota no cambia, el throughput útil puede no
   moverse: lo único que cambia es que se encolan más rápido para recibir el mismo 429.
2. **Esto afecta el criterio de aceptación de la Fase 1**, que dice que si el throughput
   no mejora "algo quedó síncrono". Con esta evidencia esa inferencia ya no es válida:
   podría no mejorar porque el techo está en OpenAI. Para separar ambas causas hay que
   medir la Fase 1 con A1 ya resuelto (reintentos con backoff ante 429) o contra un LLM
   simulado.
3. **A1 y A4 quedan confirmados con datos**, no por lectura de código: no hay backoff
   ante 429, y un 429 —que es un error transitorio y reintentable— le llega al cliente
   como `500 Internal Server Error`, sin `Retry-After` y sin forma de distinguirlo de un
   fallo permanente.

La recomendación es adelantar A1 (timeouts y reintentos) a la Fase 1, o al menos medirla
junto con ella. Queda a decisión del dueño del plan.

## Nota de entorno: hay dos PostgreSQL en esta máquina

Durante la medición se detectó que el puerto 5432 lo sirve un **PostgreSQL 17 nativo de
Windows** (servicio `postgresql-x64-17`), no el contenedor `pgvector/pgvector:pg16` del
`docker-compose.yml`. Es el nativo el que tiene los datos:

```
knowledge_base 10 · faqs 24 · incident_embeddings 7 · incidents 225
```

Detener el contenedor **no** deja al agente sin base. Importa por dos razones: la prueba
de fallo controlado de la Fase 4 ("tirar Postgres 30 s") no mide nada si se tumba el
contenedor equivocado, y quien siga el README desde cero levantaría una base distinta de
la que tiene los datos. Conviene resolverlo antes de la Fase 4.

## Verificación de B5

Con `POSTGRES_URL` apuntando a una base inalcanzable, **el proceso no arranca**: crashea
al importar con `ConnectionTimeout`, y tarda más de 150 s en hacerlo porque no hay timeout
de conexión configurado.

Consecuencia práctica: el `503` de `/ready` está implementado y probado, pero hoy es
inalcanzable en producción — el servicio no puede estar "vivo pero no listo" por culpa de
Postgres, porque directamente no llega a vivir. Lo arregla la Fase 1 al mover la
inicialización al `lifespan`.

## Qué comparar después de la Fase 1

Repetir las dos etapas con el mismo comando y anotar los resultados debajo:

- Throughput a 50 usuarios (hoy 3.94 req/s)
- p95 a 50 usuarios (hoy 17 s)
- Tasa de fallos a 50 usuarios (hoy 29.4%)
- Punto de saturación (hoy entre 10 y 50)
- **Y de qué son los fallos**: si siguen siendo 429 de OpenAI, el cambio funcionó aunque
  el throughput no suba.
