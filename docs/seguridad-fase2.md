# Resiliencia y seguridad (Fase 2)

Qué se endureció, cómo se verificó y qué quedó fuera. Las cifras de carga están en
[`baseline-carga.md`](baseline-carga.md); este documento cubre el borde del servicio.

Medido el 2026-11-15.

---

## 1. El IDOR: lo que estaba abierto

La cookie `session_id` **era** el `thread_id` del checkpointer, sin firma, sin
`HttpOnly`, sin `Secure` y sin `SameSite`. Ningún endpoint pedía credenciales. Con eso:

- Escribir la cookie a mano con el UUID de otra persona devolvía su historial completo
  de incidentes por `GET /conversation`, y permitía continuar su conversación. La
  taxonomía del sistema incluye *Seguridad*, así que lo expuesto son cuentas
  comprometidas, reglas de firewall mal configuradas y versiones vulnerables.
- `/documents/ingest/pdf` era público. Lo que escribe acaba en `knowledge_base`, que es
  lo que el agente de recomendación consulta para responderle a todos: inyectar
  contenido arbitrario ahí es prompt injection persistente contra el sistema entero.

### El arreglo, y por qué no es "firmar la cookie"

Firmar la cookie impide inventarse una conversación, pero no aísla tenants. Lo que
cierra el agujero es que el `thread_id` **deje de ser un valor que el cliente
controla**:

```
thread_id = sha256(f"{tenant_id}:{conversacion_id}")
```

La misma cookie, válida y bien firmada, presentada por otro tenant resuelve a otro
hilo. La conversación ajena no es inalcanzable por estar protegida: es inalcanzable
porque no se puede nombrar. La firma HMAC es una segunda capa, para el caso de un
atacante **dentro** del mismo tenant.

### Verificado en vivo

Dos tenants (`demo` y `soporte`), la cookie del primero presentada por el segundo:

| Quién pregunta | Cookie | Resultado |
|---|---|---|
| tenant A | la suya | su historial completo |
| **tenant B** | **la de A, válida y firmada** | **`{"messages": []}`** |
| tenant A | la suya con la firma alterada | `{"messages": []}` |

La cookie emitida: `conversacion=<uuid>.<hmac>; HttpOnly; SameSite=lax; Max-Age=2592000`.

Está también como test de integración
(`tests/integration/test_api_security.py::test_la_cookie_de_otro_tenant_no_abre_su_conversacion`),
con un doble del grafo que guarda estado por `thread_id`. Así el aislamiento se mide
sin LLM ni Postgres, y una regresión futura lo rompe en rojo.

---

## 2. Autenticación: API key por tenant

Se eligió API key sobre JWT: la API es de servicio a servicio, no hay frontend con
usuarios finales, y el JWT habría obligado a decidir refresh tokens y rotación de la
clave de firma, que el plan no cubre.

- Tabla `tenants` (`db/auth_schema.sql`) con `api_key_hash` (SHA-256), `rol` y `activo`.
- La clave en claro existe **una sola vez**: en la salida de
  `scripts/gestionar_tenants.py crear`. Una filtración de la base no entrega
  credenciales usables.
- SHA-256 y no bcrypt a propósito: bcrypt es lento por diseño porque protege
  contraseñas elegidas por humanos, que son adivinables. Una clave de 32 bytes
  aleatorios no se adivina por fuerza bruta, y un hash lento sería un costo fijo en
  cada petición.
- `/documents/ingest/pdf`, `/documents/ingest/{job_id}` y `/incidents/historical`
  exigen `rol = admin`.
- `/health`, `/ready` y `/metrics` quedan abiertos: los consulta el orquestador. Si
  `/health` pidiera credenciales, Kubernetes no podría comprobar el pod.

| Prueba | Esperado | Obtenido |
|---|---|---|
| `POST /incident` sin cabecera | 401 | 401 `no_autenticado` |
| `POST /incident` con clave inventada | 401 | 401 `no_autenticado` |
| `POST /incidents/historical` con rol `user` | 403 | 403 `sin_permiso` |
| `GET /health` sin credencial | 200 | 200 |

Un fallo de Postgres durante la verificación devuelve **503, no 401**: mandar al
cliente a revisar su clave por un problema nuestro es desviar el diagnóstico.

---

## 3. Errores: del `str(e)` al sobre con `error_id`

Antes cada endpoint hacía `HTTPException(500, detail=str(e))`. Eso devolvía al cliente
el texto crudo de la excepción —mensajes de psycopg con nombres de tabla, rutas del
filesystem, fragmentos de SQL— y además daba el mismo 500 para causas que exigen
reacciones opuestas.

`service/errors.py` separa **lo que se le dice al cliente** de **lo que se registra**.
Cada excepción declara `http_status`, un `codigo` estable y un `mensaje_publico`:

```json
{"error": {"codigo": "proveedor_no_disponible",
           "mensaje": "El servicio de análisis está saturado. Reintenta en unos segundos.",
           "error_id": "74d76f62b6de"}}
```

### La clasificación se hace por la cadena de causas, no por el tipo

Los agentes levantan con `raise ... from e`, así que lo que llega al handler es casi
siempre un envoltorio (`ErrorDeAgente`) y el dato que decide el status —un 429, un
timeout, un pool agotado— está varios niveles más abajo en `__cause__`. `clasificar()`
recorre toda la cadena.

| Causa original | Status | `Retry-After` |
|---|---|---|
| 429 rate limit del proveedor | 503 | 10 s |
| 429 `insufficient_quota` | 503 | **ninguno** |
| timeout / corte contra el proveedor | 503 | 10 s |
| `PoolTimeout`, pool cerrado, Postgres caído | 503 | 5 s |
| presupuesto del grafo agotado | 503 | 15 s |
| límite de peticiones propio | 429 | 60 s |
| lo no reconocido | 500 | ninguno |

La cuota agotada se distingue del rate limit **aunque las dos lleguen como 429**:
reintentar un rate limit sirve, reintentar una cuota agotada no, y anunciar
`Retry-After` ahí sería mentirle al cliente.

Los tipos del proveedor se identifican **por nombre de clase**, no importando el SDK de
OpenAI: así `service/errors.py` no arrastra el SDK y no se rompe si reorganiza sus
excepciones.

### El log conserva la cadena completa

El sink JSON de `service/observability.py` imprimía solo `repr` de la excepción más
externa, que con los envoltorios nuevos habría dicho "error en el agente clasificador"
y perdido el 429 que lo causó. Ahora cada línea de error lleva `cadena` (los `repr` de
toda la cadena) y `traceback` (con los "direct cause of" intactos). El `error_id` de la
respuesta es lo único técnico que viaja al cliente y es con lo que se encuentra.

---

## 4. Timeouts y presupuesto de tiempo

`ChatOpenAI` y `OpenAIEmbeddings` se instanciaban sin `timeout` ni `max_retries`, así
que heredaban los del SDK: el timeout de request ronda **los 10 minutos**. Un cuelgue de
la API dejaba una corrutina ocupada todo ese rato sin que nada apareciera como error.

- `timeout=30`, `max_retries=3` en ambos (`LLM_TIMEOUT`, `EMBEDDINGS_TIMEOUT`, etc.).
  El backoff exponencial con jitter lo implementa el SDK de OpenAI entre reintentos; no
  se escribió una política propia porque habría sido una segunda capa de reintentos
  encima de la que ya hay.
- **Presupuesto total del grafo** (`GRAFO_PRESUPUESTO_SEGUNDOS`, 120 por defecto): los
  timeouts por llamada no acotan el conjunto. Un workflow hace 5-6 llamadas al LLM más
  3 de embeddings, así que con 30 s cada una el peor caso teórico pasa de cuatro
  minutos. Un incidente real tarda 10-15 s; 120 es cuatro veces eso.

---

## 5. Rate limiting

Dos capas, con `slowapi`:

- **Por tenant, en los endpoints caros**: `30/minute` en `/incident`, `5/minute` en la
  ingesta de PDF. La clave de agrupación es el hash de la API key, no la IP: identifica
  al tenant igual de bien sin una consulta SQL por petición.
- **General** (`120/minute`) sobre las rutas sin límite propio, aplicado por middleware.

`/health`, `/ready` y `/metrics` están **exentos**, y no es un detalle: bajo carga el
orquestador sigue sondeando, así que un 429 ahí se leería como "el pod no responde" y
reiniciaría instancias sanas justo en el pico.

Verificado con `RATE_LIMIT_GENERAL=3/minute` contra `/conversation`:

```
1: 200   2: 200   3: 200   4: 429 Retry-After: 60   5: 429   6: 429
{"error":{"codigo":"limite_excedido","mensaje":"Superaste el límite de peticiones (3 per 1 minute)."}}
/health durante el bloqueo: 200 200 200 200 200
```

### Dos limitaciones conocidas

1. **El contador vive en memoria.** Con varias réplicas el límite efectivo se multiplica
   por el número de réplicas. Para un límite global hace falta darle a slowapi un
   `storage_uri` con Redis, o moverlo al gateway.
2. **El límite por tenant se comprueba después de autenticar.** El decorador de slowapi
   envuelve la función del endpoint, y FastAPI resuelve las dependencias antes de
   llamarla. Así que una avalancha de credenciales inválidas paga un `SELECT` por índice
   cada una antes de ser rechazada: el límite reparte capacidad entre tenants legítimos,
   no frena un flood anónimo. Eso es trabajo del gateway o del WAF.

El **tope de gasto diario con alerta** que pide la tarea 5 del plan **no se
implementó**: requiere un contador persistente de costo y un canal de alerta que el
proyecto no tiene, y las tarifas siguen en 0 a propósito (`LLM_COSTO_*`), así que el
contador de costo que ya existe mediría 0. Queda anotado como pendiente.

---

## 6. Imagen y secretos

**Dockerfile multi-stage.** El motivo no es el tamaño, es la superficie: `gcc` y
`libpq-dev` son herramientas de compilación, y dejarlas en la imagen de producción le
regala un compilador a cualquiera que consiga ejecución remota. La etapa final no las
tiene, corre como usuario `agente` (uid 10001) y no como root, y trae un `HEALTHCHECK`
apuntando a `/health` —no a `/ready`, que sí toca Postgres: una caída de la base
reiniciaría un contenedor sano—.

`--workers` no se fija en un número: uvicorn ya lee `WEB_CONCURRENCY`, así que el mismo
despliegue se ajusta al tamaño de la máquina sin reconstruir la imagen. **Ojo: cada
worker abre su propio pool**, así que el total de conexiones a Postgres es
`POSTGRES_POOL_MAX × WEB_CONCURRENCY`.

**Secretos.** La contraseña de Postgres estaba escrita en claro en `docker-compose.yml`
y en el README, versionada en git. Ahora el compose la lee del entorno con `${VAR:?}`,
que hace fallar `docker compose up` con un mensaje claro si falta, en vez de arrancar
con un valor por defecto que después nadie recuerda que existe. `.env.example` ya existía pero traía
la contraseña real; se reescribió con placeholders y las variables nuevas. El
`.dockerignore` también existía, y su línea más importante sigue siendo `.env`: sin ella
el build hornea las credenciales dentro de una capa de la imagen, donde quedan legibles
con `docker history`.

### Hallazgo: el `.dockerignore` anterior dejaba la imagen sin prompts

Excluía `*.md` y `docs/`. Cada agente lee su system prompt desde `prompt/*.md` **en cada
invocación**, así que la imagen se construía sin un solo prompt y el grafo habría fallado
al primer request con un `FileNotFoundError`. No se había notado porque en esta máquina la
app corre siempre desde el venv, nunca desde el contenedor —el Postgres con los datos es
el nativo de Windows, no el del compose—. El nuevo `.dockerignore` excluye solo
`docs/*.md`, que es documentación que nadie lee en runtime.

Esto es parte de por qué la tarea 6 de la Fase 3 (incluir `docs/knowledge/` en la imagen)
existe, y refuerza que construir y arrancar la imagen de verdad es trabajo de la Fase 4.

**CORS** con orígenes explícitos desde `CORS_ORIGENES`, vacío por defecto. Nunca `*`:
con `allow_credentials=True` no es válido, y la cookie de conversación tiene que viajar.

---

## 7. Criterios de aceptación

| Criterio | Estado |
|---|---|
| Un 429 de OpenAI devuelve 503 con `Retry-After`, no 500 | ✅ test de integración + unitarios |
| Los errores del cliente no contienen texto de excepción, SQL ni rutas | ✅ test que inyecta una fuga y la busca en el cuerpo |
| El log conserva la cadena de excepciones hasta la causa original | ✅ campos `cadena` y `traceback` en el sink JSON |
| Cambiar la cookie a mano no da acceso a la conversación de otro | ✅ verificado en vivo con dos tenants + test |
| Ningún secreto en el repo (`git grep` limpio) | ✅ compose, README y comentarios limpiados |
| Imagen sin `gcc`, sin root, con healthcheck | ✅ multi-stage, uid 10001, `HEALTHCHECK` |
| `pytest` y golden dataset sin cambios | ✅ 95 tests (56 → 95); golden 30/30 y 25/30, igual |

**El golden dataset no se movió**: 30/30 en categoría y 25/30 en prioridad, con los
mismos cinco casos de siempre (GD-06, GD-18, GD-21, GD-24, GD-30) y en la misma
dirección, `Baja`→`Media`. Es lo esperado: esta fase no toca prompts ni el grafo. El
sesgo de prioridad es la tarea 3 de la Fase 3.

### Lo que no se verificó

- **El 429 real del proveedor no se reprodujo contra la API.** Se intentó arrancar con
  una `OPENAI_API_KEY` inválida, pero `models/llm.py` llama `load_dotenv(override=True)`
  al importar, así que la clave del `.env` gana sobre la variable de entorno y la
  petición salió 200. La traducción está cubierta por tests deterministas en los dos
  niveles (unitario sobre `clasificar` e integración sobre la respuesta HTTP), que es
  más fiable que provocar un rate limit real, pero conviene saber que el camino
  end-to-end con un 429 genuino no se ejerció.
- **La imagen no se construyó.** El Dockerfile está reescrito y revisado pero no se
  corrió `docker build`: en esta máquina el Postgres que tiene los datos es el nativo de
  Windows, no el del compose, y levantar el stack completo no prueba lo que parece. La
  Fase 4 lo contempla.
