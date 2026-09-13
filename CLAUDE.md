# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Qué es este proyecto

Sistema multiagente de respuesta a incidentes de TI con RAG, construido con LangGraph + FastAPI + PostgreSQL/pgvector. Un grafo de agentes clasifica un incidente reportado por el usuario, recupera contexto relevante (documentación técnica + incidentes históricos resueltos) vía búsqueda vectorial, y genera recomendaciones.

## Comandos

### Entorno

```bash
docker compose up -d          # levanta Postgres con pgvector (ejecuta init.sql al crear el volumen)
python -m venv venv && venv\Scripts\activate   # Windows; source venv/bin/activate en Mac/Linux
pip install -r requirements.txt
python seed.py                 # idempotente: crea tablas vectoriales, ingesta PDFs de docs/knowledge/, carga incidentes históricos de ejemplo
```

Variables de entorno requeridas en `.env`: `OPENAI_API_KEY`, `POSTGRES_URL`. Opcionales para trazabilidad: `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`.

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

`tests/conftest.py` fija `OPENAI_API_KEY`/`POSTGRES_URL` dummy vía `os.environ.setdefault` **antes** de cualquier import de LangChain/OpenAI, para que `ChatOpenAI` y `models/llm.py` puedan instanciarse sin credenciales reales ni servicios levantados. Si agregas un test nuevo que importe algo de `agents/`, `models/` o `graphs/`, asegúrate de que pase por `conftest.py` (colócalo dentro de `tests/`).

### Evaluación del agente (no es parte de la suite de pytest)

```bash
python evaluation/run_eval.py                    # requiere el servidor corriendo (uvicorn) y OPENAI_API_KEY
python evaluation/run_eval.py --limit 3           # prueba rápida
python evaluation/run_eval.py --skip-judge        # solo métricas duras, sin costo de LLM-judge
```

Mide precisión del clasificador (category/priority/causas exactas contra `evaluation/eval_dataset.json`) y calidad de las recomendaciones vía un LLM-judge (`gpt-4o` por defecto, distinto al modelo del agente para evitar sesgo de autoevaluación). Correr esto antes/después de cambiar un prompt o de modelo para detectar regresiones.

## Arquitectura

### Flujo de un incidente

`POST /incident` (`main.py`) resuelve/crea un `session_id` por cookie, arma el `IncidentState` (nuevo o incremental) y llama a `incident_app.invoke(...)`, el grafo de LangGraph compilado en `graphs/incidente_graph.py` con checkpointer Postgres (persiste el estado de la conversación por `thread_id=session_id`).

El grafo **no tiene un flujo lineal fijo**: el nodo `orchestrator` es el entry point y se re-visita después de cada agente para decidir el siguiente paso:

```
orchestrator ──router()──> classifier ──> orchestrator ──> recommendation ──> [tools?] ──> recommendation ──> END
                ├────────> faq ──────────────────────────────────────────────────────────────────────────> END
                └────────> END (si ya terminó)
```

- **`orchestrator_agent`** (`agents/orchestrator_agent.py`): decide `next_agent` ∈ `{classifier, recommendation, faq, end}`. No resuelve nada del incidente. Antes de consultar al LLM hace un **pre-chequeo determinístico** (`_coincide_con_faq_documentada`): busca el mensaje en la tabla `faqs` y, si supera `FAQ_ROUTING_THRESHOLD`, enruta a `faq` sin gastar una llamada al LLM. Solo corre con `current_step is None`, para no secuestrar un workflow de incidente en curso. Si no hay match, decide el LLM con `structured_output(OrquestatorOutput)`.
- **`classifier_agent`**: determina `category`, `priority`, `possible_causes` (structured output), marca `current_step="classifier_done"`, y por edge fijo vuelve a `orchestrator`.
- **`recomendation_agent`**: es el único nodo con tools bindeadas (`models/llm.py: llm_bind_tools`). Se ejecuta en dos pasadas dentro del mismo `invoke`: la primera pide en paralelo `search_knowledge_base_rag`, `search_similar_incidents_rag` e `insert_incident`; `recommendation_router` detecta `tool_calls` pendientes y desvía al nodo `tools` (`ToolNode`); tras ejecutarlas, vuelve a `recomendation_agent`, que en la segunda pasada (detecta `ToolMessage`s en el historial) sintetiza la respuesta final y marca `current_step="recommendation_done"`.
- **`faq_agent`**: camino paralelo, desacoplado del flujo de incidentes — no clasifica ni registra nada. **No usa tool-calling**: la búsqueda vectorial contra `faqs` la ejecuta el propio código como paso obligatorio, antes de decidir qué hacer. Resuelve por una de tres ramas según la similitud del mejor candidato: sin resultados → invita a dar más detalle; por encima de `FAQ_HIGH_CONFIDENCE_THRESHOLD` (env var, default 0.75) → devuelve el `answer` almacenado tal cual, sin llamar al LLM; en el medio → una única llamada al LLM con los candidatos como contexto. Siempre termina en una pasada (`add_edge("faq", END)`).
- **`graphs/router.py`**: función de routing trivial, solo lee `state["next_agent"]` (la decisión real vive en el LLM del orquestador, no en código).

La distinción FAQ vs. clasificador es el punto de mayor ambigüedad del sistema, y se resuelve en dos capas:

1. **Pre-chequeo determinístico** (≥ `FAQ_ROUTING_THRESHOLD`, default 0.85): si la pregunta está literalmente documentada en `faqs`, va a `faq`. Existe porque el criterio por redacción fallaba con FAQs escritas en primera persona ("¿Por qué mi equipo tarda tanto en iniciar?"), que el LLM leía como síntoma activo y mandaba a `classifier`.
2. **Criterio del LLM** (si no hubo match): no es si el mensaje tiene forma de pregunta, sino si el usuario reporta un problema activo (→ `classifier`) o pide información general de procedimiento (→ `faq`). Los ejemplos que fijan el criterio están en `prompt/orquestator.md`; ante la duda indica preferir `classifier`.

Los dos umbrales están separados a propósito. Medido contra la base real: las preguntas verbatim del `faqs.md` dan ~100% de similitud, mientras que los parafraseos de un síntoma activo caen en 0.47–0.75. El 0.85 se ubica en la banda vacía entre ambos grupos, así que el pre-chequeo atrapa lo documentado sin robarle casos ambiguos al criterio del LLM. Si cambias el contenido de `faqs.md`, vale volver a medir esa separación.

Al agregar un agente nuevo al grafo: no lo conectes directamente a otro agente de negocio — todo pasa por el orquestador. Actualiza las reglas de routing en `prompt/orquestator.md` (el enrutamiento es dirigido por prompt, no por lógica en `router.py`) y el `Literal` en `schemas/models.py::OrquestatorOutput`.

### Persistencia de conversación

El estado (`state/state.py::IncidentState`, extiende `MessagesState` de LangGraph) se persiste completo por sesión vía `PostgresSaver`. En una conversación nueva se manda el estado completo; en una continuación solo se manda el nuevo `HumanMessage` (el reducer `add_messages` lo concatena) y se resetea `current_step=None` para forzar una nueva pasada de clasificación.

### RAG y tools

Tres tablas vectoriales en pgvector (`database/vector_db.py`; esquemas en `db/vector_schema.sql` y `db/faq_schema.sql`, ambos ejecutados por `initialize_vector_tables()`):
- `knowledge_base` — chunks de PDFs ingeridos vía `/documents/ingest/pdf` o `seed.py` (docs en `docs/knowledge/`). Es la única fragmentada; una fila = un chunk.
- `incident_embeddings` — incidentes históricos resueltos, agregables vía `/incidents/historical`. Una fila = un caso completo.
- `faqs` — preguntas frecuentes. Una fila = un caso completo. Se pueblan parseando `docs/knowledge/faqs.md` con `service/faq_loader.py` (parseo estructural exacto sobre una convención Markdown documentada en el propio archivo — sin heurísticas ni LLM).

Ambas usan similarity search por coseno con un umbral (`similarity_threshold=0.40` por defecto). `tools/rag_tools.py` expone estas búsquedas como `@tool` de LangChain para que el LLM las invoque; `tools/incidente_tools.py` expone operaciones SQL directas sobre la tabla relacional `incidents` (`database/db.py`, distinta conexión de la vectorial aunque sea el mismo Postgres).

### Prompts

Cada agente lee su system prompt desde un `.md` en `prompt/` en cada invocación (no se cachean en memoria) — para cambiar el comportamiento de un agente, edita el `.md` correspondiente, no hace falta tocar el código Python del agente.

### Convención de logging

Todos los agentes/tools usan `loguru` con prefijos identificando el componente: `[ORQUESTADOR]`, `[CLASIFICADOR]`, `[RECOMENDACION]`, `[DB]`, `[RAG-KB]`, `[RAG-HIST]`. Se loguea duración de las llamadas al LLM/DB con `time.perf_counter()`.
