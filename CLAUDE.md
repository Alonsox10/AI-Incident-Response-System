# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Qué es este proyecto

Sistema multiagente de respuesta a incidentes de TI con RAG, construido con LangGraph + FastAPI + PostgreSQL/pgvector. Un grafo de agentes clasifica un incidente reportado por el usuario, recupera contexto relevante (documentación técnica + incidentes históricos resueltos) vía búsqueda vectorial, y genera recomendaciones.

## Antes de empezar: verifica que los archivos existan

**El repo vive dentro de OneDrive y se han observado archivos desapareciendo solos**, repetidamente y sin que nadie los borre: `evaluation/` se perdió entera dos veces y `golden_dataset/README.md` dos veces más, incluso minutos después de haber verificado que estaban en disco. No hay hooks configurados y escribir por shell en esas carpetas funciona, así que el sospechoso es la sincronización.

Consecuencias prácticas:

- **Este documento puede describir archivos que hoy no están.** Si una ruta mencionada acá no existe, probablemente desapareció, no es que nunca se escribió. Compruébalo con `git log --diff-filter=D --name-only -3` y `git status` antes de concluir nada.
- **Tras escribir un archivo nuevo, verifica que siga ahí** (`test -f`). Una escritura puede reportar éxito y el archivo no quedar.
- **Commitear es la única protección real.** Lo que no está en git se pierde de verdad: `evaluation/run_flow_eval.py` y `flow_dataset.json` hubo que reconstruirlos desde cero porque nunca llegaron a un commit.

## Comandos

### Entorno

```bash
docker compose up -d          # levanta Postgres con pgvector (ejecuta init.sql al crear el volumen)
python -m venv venv && venv\Scripts\activate   # Windows; source venv/bin/activate en Mac/Linux
pip install -r requirements.txt
python seed.py                 # idempotente: crea las tablas vectoriales, ingesta PDFs de docs/knowledge/, carga incidentes históricos y parsea faqs.md
```

Variables de entorno en `.env`:
- Requeridas: `OPENAI_API_KEY`, `POSTGRES_URL`.
- Trazabilidad (opcionales): `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`.
- Umbrales del camino de FAQ (opcionales): `FAQ_HIGH_CONFIDENCE_THRESHOLD` (default 0.75) y `FAQ_ROUTING_THRESHOLD` (default 0.85). Ver la sección de arquitectura: están separados a propósito.

**Gotcha al editar `docs/knowledge/faqs.md`:** `seed.py` es idempotente *a nivel de tabla* (`_faqs_ya_cargadas()` solo mira si `faqs` tiene filas), así que re-correrlo tras editar el archivo **no recarga nada**. Para aplicar cambios hay que vaciar la tabla primero: `TRUNCATE faqs;` y después `python seed.py`. Lo mismo aplica a los incidentes históricos.

### Correr la app

```bash
uvicorn main:app --reload      # http://127.0.0.1:8000, docs en /docs
```

### Tests

```bash
pytest                                    # corre todo (testpaths=tests, pythonpath=. vía pytest.ini)
pytest tests/unit/test_classifier.py      # un solo archivo
pytest tests/unit/test_classifier.py::test_nombre_del_test   # un solo test
pytest tests/integration                  # solo integración
```

En Windows, con el venv sin activar, invocar el intérprete directo: `./venv/Scripts/python.exe -m pytest -q`. Lo mismo para los scripts de `evaluation/` y `golden_dataset/` — usan dependencias que solo están en el venv.

**La suite es hermética y debe seguir siéndolo.** `tests/conftest.py` hace dos cosas, en este orden exacto, antes de cualquier import de LangChain/OpenAI:

1. Neutraliza `dotenv.load_dotenv` (`dotenv.load_dotenv = lambda *a, **k: False`).
2. Fija `OPENAI_API_KEY`/`POSTGRES_URL` dummy con `os.environ.setdefault`.

El paso 1 no es opcional: `database/db.py`, `models/llm.py` y `service/embedding_service.py` llaman `load_dotenv(override=True)` a nivel de import, lo que **pisaba los dummies con las credenciales reales del `.env`** y hacía que la suite gastara API de OpenAI y consultara el Postgres real sin que se notara. Que los tests pasen con credenciales bogus es la prueba de que nadie sale a la red — si alguna vez la suite empieza a tardar varios segundos de más, sospecha de esto.

Al escribir un test que toque `agents/`, `models/` o `graphs/`: colócalo dentro de `tests/` (para que aplique el conftest) y mockea toda llamada externa. Ojo con `agents.orchestrator_agent._coincide_con_faq_documentada`, que pega a embeddings + Postgres en cada invocación del orquestador con `current_step is None`; `tests/unit/test_orchestrator.py` lo neutraliza con un fixture `autouse`, y los tests de integración lo parchean caso por caso.

### Golden dataset — correr siempre junto con pytest

**"Hacer test" en este proyecto = `pytest` + el golden dataset.** `pytest` corre con todo mockeado, así que puede estar en verde mientras la clasificación real se degrada; el golden set es el único que ejerce al clasificador contra un LLM real con ground truth.

```bash
python golden_dataset/run_golden.py              # 30 incidentes, categoría + prioridad
python golden_dataset/run_golden.py --limit 5    # prueba rápida
```

No necesita Postgres ni el servidor, solo `OPENAI_API_KEY` (~30 llamadas, ~35 s). Sale con código 1 si falla algún caso. Detalles y línea base en `golden_dataset/README.md`.

> El ground truth no se ajusta para que dé verde. Si un caso falla, se decide si estaba mal la expectativa (se corrige el caso y se anota por qué) o el sistema (se corrige el prompt).

### Evaluación del agente (no es parte de la suite de pytest)

Dos evaluaciones más pesadas, que se corren cuando el cambio las toca — ver `evaluation/README.md`, que además guarda la línea base vigente:

```bash
python evaluation/run_flow_eval.py               # FLUJO: en proceso, solo requiere Postgres + seed
python evaluation/run_eval.py                    # CONTENIDO: requiere el servidor corriendo (uvicorn)
python evaluation/run_eval.py --skip-judge       # solo métricas duras, sin costo de LLM-judge
```

- `run_eval.py` mide **contenido**: precisión de category/priority contra `eval_dataset.json` y calidad de las recomendaciones vía LLM-judge (`gpt-4o`, distinto al del agente para evitar autoevaluación sesgada).
- `run_flow_eval.py` mide **flujo**: envuelve el pre-chequeo del orquestador, la búsqueda de FAQs y las funciones de RAG para observar qué agente atendió, qué tools se invocaron y qué rama tomó FAQ. Una respuesta puede ser correcta y aun así haber recorrido mal el grafo (costando 3× y registrando un incidente falso); por eso hacen falta las dos.

Correr ambas antes/después de cambiar un prompt, un umbral o el modelo. Al agregar una capacidad nueva, agregarle casos al dataset correspondiente: si no, la línea base queda ciega justo donde el sistema creció.

## Arquitectura

### Flujo de un incidente

`POST /incident` (`main.py`) resuelve/crea un `session_id` por cookie, arma el `IncidentState` (nuevo o incremental) y llama a `incident_app.invoke(...)`, el grafo de LangGraph compilado en `graphs/incidente_graph.py` con checkpointer Postgres (persiste el estado de la conversación por `thread_id=session_id`).

El grafo **no tiene un flujo lineal fijo**: el nodo `orchestrator` es el entry point y se re-visita después de cada agente para decidir el siguiente paso:

```
orchestrator ──router()──> classifier ──> orchestrator ──> recommendation ──> [tools?] ──> recommendation ──> END
                │                            └── (reporte sin síntoma) ──> orchestrator ──> END
                ├────────> faq ──────────────────────────────────────────────────────────────────────────> END
                └────────> END (si ya terminó)
```

Hay tres formas de terminar, y conviene distinguirlas porque solo una registra el incidente: `recommendation_done` (diagnóstico completo, con `insert_incident`), `faq_done` (respuesta de FAQ, sin registro) y `needs_detail` (el clasificador pidió más información, sin registro ni RAG).

- **`orchestrator_agent`** (`agents/orchestrator_agent.py`): decide `next_agent` ∈ `{classifier, recommendation, faq, end}`. No resuelve nada del incidente. Antes de consultar al LLM hace un **pre-chequeo determinístico** (`_coincide_con_faq_documentada`): busca el mensaje en la tabla `faqs` y, si supera `FAQ_ROUTING_THRESHOLD`, enruta a `faq` sin gastar una llamada al LLM. Solo corre con `current_step is None`, para no secuestrar un workflow de incidente en curso. Si no hay match, decide el LLM con `structured_output(OrquestatorOutput)`.
- **`classifier_agent`**: determina `category`, `priority`, `possible_causes` (structured output), marca `current_step="classifier_done"`, y por edge fijo vuelve a `orchestrator`. El schema incluye `informacion_suficiente`: cuando el mensaje no trae un síntoma concreto ("algo no funciona"), el agente **descarta** la clasificación —sería una etiqueta inventada—, responde pidiendo detalle y marca `current_step="needs_detail"`, que el orquestador enruta a `end`. Así el reporte vacío no consulta el RAG ni registra un incidente.
- **`recomendation_agent`**: es el único nodo con tools bindeadas (`models/llm.py: llm_bind_tools`). Se ejecuta en dos pasadas dentro del mismo `invoke`: la primera pide en paralelo `search_knowledge_base_rag`, `search_similar_incidents_rag` e `insert_incident`; `recommendation_router` detecta `tool_calls` pendientes y desvía al nodo `tools` (`ToolNode`); tras ejecutarlas, vuelve a `recomendation_agent`, que en la segunda pasada (detecta `ToolMessage`s en el historial) sintetiza la respuesta final y marca `current_step="recommendation_done"`.
- **`faq_agent`**: camino paralelo, desacoplado del flujo de incidentes — no clasifica ni registra nada. **No usa tool-calling**: la búsqueda vectorial contra `faqs` la ejecuta el propio código como paso obligatorio, antes de decidir qué hacer. Resuelve por una de tres ramas según la similitud del mejor candidato: sin resultados → invita a dar más detalle; por encima de `FAQ_HIGH_CONFIDENCE_THRESHOLD` (env var, default 0.75) → devuelve el `answer` almacenado tal cual, sin llamar al LLM; en el medio → una única llamada al LLM con los candidatos como contexto. Siempre termina en una pasada (`add_edge("faq", END)`).
- **`graphs/router.py`**: función de routing trivial, solo lee `state["next_agent"]` (la decisión real vive en el LLM del orquestador, no en código).

La distinción FAQ vs. clasificador es el punto de mayor ambigüedad del sistema, y se resuelve en dos capas:

1. **Pre-chequeo determinístico** (≥ `FAQ_ROUTING_THRESHOLD`, default 0.85): si la pregunta está literalmente documentada en `faqs`, va a `faq`. Existe porque el criterio por redacción fallaba con FAQs escritas en primera persona ("¿Por qué mi equipo tarda tanto en iniciar?"), que el LLM leía como síntoma activo y mandaba a `classifier`.
2. **Criterio del LLM** (si no hubo match): no es si el mensaje tiene forma de pregunta, sino si el usuario reporta un problema activo (→ `classifier`) o pide información general de procedimiento (→ `faq`). Los ejemplos que fijan el criterio están en `prompt/orquestator.md`; ante la duda indica preferir `classifier`.

Los dos umbrales están separados a propósito. Medido contra la base real: las preguntas verbatim del `faqs.md` dan ~100% de similitud, mientras que los parafraseos de un síntoma activo caen en 0.47–0.75. El 0.85 se ubica en la banda vacía entre ambos grupos, así que el pre-chequeo atrapa lo documentado sin robarle casos ambiguos al criterio del LLM. Si cambias el contenido de `faqs.md`, vale volver a medir esa separación.

Al agregar un agente nuevo al grafo: no lo conectes directamente a otro agente de negocio — todo pasa por el orquestador. Actualiza las reglas de routing en `prompt/orquestator.md` (el enrutamiento es dirigido por prompt, no por lógica en `router.py`) y el `Literal` en `schemas/models.py::OrquestatorOutput`.

### Taxonomía cerrada

`schemas/models.py` define `IncidentCategory` (Error backend, Error frontend, Infraestructura, Redes, Seguridad) e `IncidentPriority` (Alta, Media, Baja) como `Literal`. **No son etiquetas libres, y el cierre es deliberado**: `tools/incidente_tools.py::search_incident_by_category` filtra con `WHERE category = %s` —igualdad exacta—, así que cualquier variante que el modelo inventara fragmentaría el histórico sin que nada fallara visiblemente. El `Literal` convierte ese error silencioso en uno imposible: la API de salidas estructuradas restringe la generación al enum.

Para cambiar la taxonomía hay que tocar tres sitios a la vez, o el sistema queda incoherente: el `Literal` en `schemas/models.py`, las categorías y criterios de prioridad en `prompt/classify_agent.md`, y los casos de `golden_dataset/incidents.json` (que declara la taxonomía vigente en su bloque `taxonomia`).

**Estado conocido (2026-09-28):** el clasificador acierta la categoría 30/30 pero la prioridad 26/30, y los 4 fallos son el mismo patrón — casos `Baja` que eleva a `Media`, nunca al revés. La causa está en `prompt/classify_agent.md`: los criterios de `Media` ("afecta a un subconjunto de usuarios") y `Baja` ("afecta a muy pocos usuarios") se solapan, y el único ejemplo de `Baja` del prompt es cosmético (estilos CSS), así que el modelo no tiene de dónde inferir que un caso funcional con un solo usuario afectado también es `Baja`. Si corres el golden dataset y ves 26/30 en prioridad, es esto y no una regresión nueva.

### Persistencia de conversación

El estado (`state/state.py::IncidentState`, extiende `MessagesState` de LangGraph) se persiste completo por sesión vía `PostgresSaver`. En una conversación nueva se manda el estado completo; en una continuación solo se manda el nuevo `HumanMessage` (el reducer `add_messages` lo concatena) y se resetea `current_step=None` para forzar una nueva pasada de clasificación.

### RAG y tools

Tres tablas vectoriales en pgvector (`database/vector_db.py`; esquemas en `db/vector_schema.sql` y `db/faq_schema.sql`, concatenados y ejecutados en ese orden por `initialize_vector_tables()`, que corre al importar `graphs/incidente_graph.py`). El orden importa: `CREATE EXTENSION vector` vive solo en `vector_schema.sql`, así que `faq_schema.sql` no es autosuficiente contra una base limpia.
- `knowledge_base` — chunks de PDFs ingeridos vía `/documents/ingest/pdf` o `seed.py` (docs en `docs/knowledge/`). Es la única fragmentada; una fila = un chunk.
- `incident_embeddings` — incidentes históricos resueltos, agregables vía `/incidents/historical`. Una fila = un caso completo.
- `faqs` — preguntas frecuentes. Una fila = un caso completo. Se pueblan parseando `docs/knowledge/faqs.md` con `service/faq_loader.py` (parseo estructural exacto sobre una convención Markdown documentada en el propio archivo — sin heurísticas ni LLM).

Las tres usan similarity search por coseno con un umbral (`similarity_threshold=0.40` por defecto). `tools/rag_tools.py` expone las búsquedas sobre `knowledge_base` e `incident_embeddings` como `@tool` de LangChain para que el LLM las invoque; la de `faqs` **no** se expone como tool (la llama directo `faq_agent`, y también el pre-chequeo del orquestador). `tools/incidente_tools.py` expone operaciones SQL directas sobre la tabla relacional `incidents` (`database/db.py`, distinta conexión de la vectorial aunque sea el mismo Postgres).

### Prompts

Cada agente lee su system prompt desde un `.md` en `prompt/` en cada invocación (no se cachean en memoria) — para cambiar el comportamiento de un agente, edita el `.md` correspondiente, no hace falta tocar el código Python del agente.

### Convención de logging

Todos los agentes/tools usan `loguru` con prefijos identificando el componente: `[ORQUESTADOR]`, `[CLASIFICADOR]`, `[RECOMENDACION]`, `[FAQ]`, `[FAQ-LOADER]`, `[DB]`, `[RAG-KB]`, `[RAG-HIST]`. Se loguea duración de las llamadas al LLM/DB con `time.perf_counter()`.

Los logs son la forma más rápida de ver qué camino tomó una consulta: `[ORQUESTADOR] Decision: faq | match documentado=93%` indica que resolvió el pre-chequeo sin LLM, y `[FAQ] Coincidencia directa` que devolvió la respuesta almacenada sin generar texto.

Si ves `Failed to POST .../runs/multipart ... 403` en cada corrida, es la `LANGSMITH_API_KEY` del `.env` rechazada: ensucia la salida pero no afecta ningún resultado. Se silencia quitando `LANGSMITH_TRACING` del `.env`.
