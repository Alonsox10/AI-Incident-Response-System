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

El mensaje completo identifica la causa exacta:

```
Error code: 429 - Rate limit reached for gpt-4o-mini in organization org-… on
tokens per min (TPM): Limit 2000000, Used 1992384, Requested 12080.
Please try again in 133ms.          code: 'rate_limit_exceeded', type: 'tokens'
```

**No es falta de saldo.** Es `rate_limit_exceeded` sobre el presupuesto de **tokens por minuto**, no `insufficient_quota`. La cuenta tiene un límite de **2.000.000 TPM** y lo estábamos consumiendo al 99,6%.

La aritmética cierra con lo medido en `/metrics`: **~8.900 tokens por incidente** (8.182 de entrada + 688 de salida).

| Prueba | Throughput | Tokens/min | % de la cuota | Fallos |
|---|---:|---:|---:|---:|
| 10 usuarios | 0,87 req/s | ~463.000 | 23% | 0% |
| 50 usuarios | 3,94 req/s | ~2.100.000 | **105%** | 29% |

El techo teórico es `2.000.000 ÷ 8.900 ≈ 3,7 req/s`, y medimos 3,94. La cuota y el techo de los 40 hilos coinciden por casualidad alrededor de 4 req/s.

**Y los 429 eran recuperables**: OpenAI pedía esperar entre **45 y 133 ms**. Un backoff trivial habría absorbido los 104 fallos sin que ningún usuario se enterara. No son 104 peticiones imposibles, son 104 que nadie reintentó.

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

---

# Resultados DESPUÉS de la Fase 1 — 2026-11-07

Mismo comando, misma máquina, mismo modelo. Camino de request íntegramente asíncrono,
pool de conexiones y checkpointer `AsyncPostgresSaver`.

| Usuarios | Throughput | p50 | p95 | Fallos |
|---:|---:|---:|---:|---:|
| 10 | 0,67 req/s | 14,0 s | 18,0 s | **0%** |
| 50 | 2,99 req/s | 14,0 s | 21,0 s | **1,5%** (4 de 269) |

Comparado con la línea base:

| Métrica (50 usuarios) | Antes | Después | |
|---|---:|---:|---|
| Tasa de fallos | 29,4% | **1,5%** | **20× mejor** |
| Throughput bruto | 3,94 req/s | 2,99 req/s | peor en apariencia |
| Throughput **útil** (sin fallos) | 2,78 req/s | **2,95 req/s** | mejor |
| p95 | 17 s | 21 s | peor |

## Por qué el throughput bruto bajó y aun así esto es una mejora

**El 3,94 req/s de la línea base estaba inflado por los fallos.** Un request que recibe
429 termina en ~3 s en vez de los ~12 s de uno completo, así que el 29% de peticiones
fallidas subía artificialmente el promedio. Contando solo las que devolvieron una
respuesta útil, el throughput pasó de 2,78 a 2,95 req/s.

El p95 sube por el mismo motivo: antes casi un tercio de los requests "terminaba" rápido
porque fracasaba. Ahora se completan todos, y completarse cuesta ~15 s.

**La métrica honesta aquí es la tasa de error**, y cayó de 29,4% a 1,5%.

## Lo que esta prueba NO demuestra

No demuestra que el techo de concurrencia haya subido, y conviene decirlo claro:

- Con 50 usuarios apenas se supera el límite de 40 hilos de AnyIO que tenía la versión
  síncrona. Para ver la diferencia haría falta probar con 200-500 usuarios.
- Pero a 50 usuarios ya se roza la cuota TPM. Subir a 200 solo produciría más 429, que
  es un límite del proveedor y no del proceso.

Dicho de otro modo: **el techo dejó de estar en la aplicación y pasó a estar en la cuota
de OpenAI**, que era el objetivo de la fase, pero esta prueba no puede cuantificar cuánto
subió porque no hay margen de cuota para medirlo. Para hacerlo habría que usar un doble
del LLM (Pista A), que se descartó por decisión del dueño del plan el 2026-10-17.

## Verificaciones binarias de la Fase 1

| Criterio | Resultado |
|---|---|
| Ninguna llamada bloqueante en el camino de un request | ✅ auditado programáticamente: los 4 agentes, las 4 tools, embeddings y las 7 funciones de `vector_db` son `async` |
| La app arranca con Postgres caído | ✅ arranca y responde `/health` 200, `/ready` 503. Antes crasheaba al importar con `ConnectionTimeout` |
| Se recupera sola cuando la base vuelve | ✅ cubierto por `tests/unit/test_db_pool.py`; ⚠️ no verificado contra una base real (ver abajo) |
| `pytest` sin regresiones | ✅ 56/56 (eran 50; +6 del pool) |
| Golden dataset sin cambios | ✅ categoría 30/30, prioridad 25/30 — igual que al cerrar la Fase 0 |

### Sobre la recuperación automática

Durante la fase se encontró y corrigió un bug real: cuando `open()` del pool agotaba el
timeout, **psycopg cerraba el pool pero el módulo seguía guardando la referencia**, así
que todas las llamadas posteriores fallaban con "the pool is already closed" y el proceso
quedaba muerto hasta reiniciarlo — justo lo contrario de lo que la fase busca. Ahora un
pool fallido o cerrado se descarta y el siguiente intento crea uno nuevo.

La lógica está cubierta por tests deterministas. **No se validó contra una base real**: el
intento de simularlo con un proxy TCP falló porque el proxy no soportaba las conexiones
concurrentes del pool, y tirar el PostgreSQL nativo de la máquina quedó descartado por
afectar al entorno del usuario. Queda pendiente para la Fase 4, donde el plan ya contempla
una prueba de fallo controlado — y donde primero hay que resolver la ambigüedad de los dos
PostgreSQL descrita arriba.

---

## Qué comparar después de la Fase 1

Repetir las dos etapas con el mismo comando y anotar los resultados debajo:

- Throughput a 50 usuarios (hoy 3.94 req/s)
- p95 a 50 usuarios (hoy 17 s)
- Tasa de fallos a 50 usuarios (hoy 29.4%)
- Punto de saturación (hoy entre 10 y 50)
- **Y de qué son los fallos**: si siguen siendo 429 de OpenAI, el cambio funcionó aunque
  el throughput no suba.
