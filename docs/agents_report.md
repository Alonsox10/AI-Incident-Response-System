# Reporte de Agentes — AI Incident Response System

> Generado el: 2026-06-16  
> Resultado general: **23/23 pruebas aprobadas** (19 unitarias + 4 de integración)

---

## 1. Classifier Agent

### Nombre
`classifier_agent` — definido en [agents/classifier_agent.py](../agents/classifier_agent.py)

### Funcionalidad
Analiza la descripción de un incidente y lo clasifica en tres dimensiones:

| Campo | Tipo | Descripción |
|---|---|---|
| `category` | `str` | Categoría del incidente (ej. "Error backend", "Seguridad", "Infraestructura") |
| `priority` | `str` | Nivel de severidad (High / Medium / Low) |
| `possible_causes` | `list[str]` | Lista de posibles causas raíz |
| `current_step` | `str` | Siempre retorna `"classifier_done"` para indicar que terminó |

El agente lee su prompt desde `prompt/classify_agent.md`, toma el último mensaje del usuario en el estado compartido y utiliza un LLM con salida estructurada (`llm.with_structured_output(IncidentClassificationOutput)`) para garantizar que la respuesta siempre cumpla el esquema `IncidentClassificationOutput`.

### Relación con otros agentes

```
Orchestrator Agent
      │
      │  (decide enrutar a classifier)
      ▼
 Classifier Agent  ──── popula category, priority, possible_causes ────▶  Orchestrator Agent
                                                                              (siguiente decisión)
```

- **Precedido por:** `orchestrator_agent`, que evalúa el estado y decide llamar al clasificador cuando `current_step` es `None`.
- **Seguido por:** `orchestrator_agent` nuevamente, que al ver `current_step = "classifier_done"` decide enrutar al agente de recomendación.
- **No interactúa directamente** con `recomendation_agent`, pero sus salidas (`category`, `priority`) son consumidas por él.

### Posibles errores

| Error | Causa | Comportamiento |
|---|---|---|
| `ValueError("Ocurrió un error en el agente clasificador.")` | Cualquier excepción interna (fallo del LLM, archivo de prompt no encontrado, estado malformado) | Se captura con `except Exception`, se registra en el logger y se relanza como `ValueError` |
| `KeyError` | Si `state["messages"]` está vacío o no existe | Provoca el `ValueError` anterior al intentar `state["messages"][-1]` |
| `FileNotFoundError` | Si `prompt/classify_agent.md` no existe en el directorio de ejecución | Provoca el `ValueError` anterior |
| `ValidationError` (Pydantic) | Si el LLM retorna un output que no cumple `IncidentClassificationOutput` | Capturado como excepción genérica y envuelto en `ValueError` |
| Warning de compatibilidad | `gpt-4` no soporta `json_schema`, cae a `function_calling` automáticamente | No es un error bloqueante, solo un `UserWarning` de `langchain_openai` |

### Pruebas realizadas

**Archivo:** [tests/unit/test_classifier.py](../tests/unit/test_classifier.py)  
**Total: 7 pruebas — todas PASSED**

| # | Nombre del test | Qué verifica | Resultado |
|---|---|---|---|
| 1 | `test_classifies_backend_incident` | Que retorna `category = "Error backend"` ante un incidente de backend | PASSED |
| 2 | `test_classifies_security_incident` | Que retorna `category = "Seguridad"` ante un incidente de seguridad | PASSED |
| 3 | `test_classifies_infrastructure_incident` | Que retorna `category = "Infraestructura"` ante un incidente de infraestructura | PASSED |
| 4 | `test_returns_list_of_possible_causes` | Que `possible_causes` es siempre una lista | PASSED |
| 5 | `test_always_sets_current_step_to_classifier_done` | Que `current_step` siempre es `"classifier_done"` | PASSED |
| 6 | `test_returns_all_required_keys` | Que la respuesta contiene `category`, `priority`, `possible_causes` y `current_step` | PASSED |
| 7 | `test_raises_value_error_on_llm_failure` | Que lanza `ValueError` cuando el LLM falla | PASSED |

**Estrategia de prueba:** Se mockea `agents.classifier_agent.llm_structured` para simular respuestas del LLM sin realizar llamadas reales a la API.

---

## 2. Orchestrator Agent

### Nombre
`orchestrator_agent` — definido en [agents/orchestrator_agent.py](../agents/orchestrator_agent.py)

### Funcionalidad
Es el punto de entrada y el enrutador central del workflow. Se ejecuta **dos veces** en cada flujo normal:

1. **Primera ejecución:** Lee el mensaje del usuario y el estado vacío → decide enrutar a `classifier`.
2. **Segunda ejecución:** Lee el estado ya clasificado (`current_step = "classifier_done"`) → decide enrutar a `recommendation`.

El agente construye un contexto de workflow que incluye `category`, `priority`, `recommendations` y `current_step`, y se lo envía al LLM junto con el prompt de `prompt/orquestator.md`. El LLM retorna una decisión estructurada con `next_agent` ∈ `{"classifier", "recommendation", "end"}`.

| Campo retornado | Tipo | Valores posibles |
|---|---|---|
| `next_agent` | `Literal` | `"classifier"` / `"recommendation"` / `"end"` |

### Relación con otros agentes

```
         ┌──────────────────────────────────────┐
         │          Orchestrator Agent           │
         │  (entry point del StateGraph)         │
         └──────┬──────────────┬────────────────┘
                │              │
     next_agent=│"classifier"  │ next_agent="end"
                ▼              ▼
       Classifier Agent      END
                │
                │ (regresa al orchestrator)
                ▼
       Orchestrator Agent
                │
     next_agent=│"recommendation"
                ▼
      Recommendation Agent
                │
                ▼
           Tools Node
                │
                ▼
              END
```

- **Controla el flujo completo** del grafo LangGraph (`graphs/incidente_graph.py`).
- La función `router` en [graphs/router.py](../graphs/router.py) lee `state["next_agent"]` y lo usa como edge condicional.
- Es el único agente que decide si el clasificador y el recomendador se ejecutan o no.

### Posibles errores

| Error | Causa | Comportamiento |
|---|---|---|
| `ValueError("Ocurrió un error en el agente orquestador.")` | Cualquier excepción interna | Capturada con `except Exception`, registrada y relanzada |
| Bucle infinito | Si el LLM nunca retorna `"end"` | El grafo no tiene límite de iteraciones explícito; podría ciclar |
| `FileNotFoundError` | Si `prompt/orquestator.md` no existe | Provoca el `ValueError` anterior |
| Decisión incorrecta del LLM | Si el modelo elige mal el siguiente agente | No hay validación post-LLM del valor retornado más allá del tipo Pydantic |
| Warning de compatibilidad | `gpt-4` no soporta `json_schema` | `UserWarning` no bloqueante, cae a `function_calling` automáticamente |

### Pruebas realizadas

**Archivo:** [tests/unit/test_orchestrator.py](../tests/unit/test_orchestrator.py)  
**Total: 6 pruebas — todas PASSED**

| # | Nombre del test | Qué verifica | Resultado |
|---|---|---|---|
| 1 | `test_routes_to_classifier_when_no_step` | Que retorna `next_agent = "classifier"` cuando `current_step` es `None` | PASSED |
| 2 | `test_routes_to_recommendation_after_classifier` | Que retorna `next_agent = "recommendation"` cuando `current_step = "classifier_done"` | PASSED |
| 3 | `test_routes_to_end_when_workflow_complete` | Que retorna `next_agent = "end"` cuando el workflow está completo | PASSED |
| 4 | `test_response_contains_next_agent_key` | Que la respuesta siempre contiene la clave `next_agent` | PASSED |
| 5 | `test_llm_is_called_once_per_invocation` | Que el LLM se llama exactamente una vez por invocación | PASSED |
| 6 | `test_raises_value_error_on_llm_failure` | Que lanza `ValueError` cuando el LLM falla | PASSED |

**Estrategia de prueba:** Se mockea `agents.orchestrator_agent.llm_structured` para controlar la decisión de enrutamiento sin llamadas reales a la API.

---

## 3. Recommendation Agent

### Nombre
`recomendation_agent` — definido en [agents/recomendation_agent.py](../agents/recomendation_agent.py)

### Funcionalidad
Genera recomendaciones accionables basadas en el incidente ya clasificado. Utiliza un LLM con herramientas (`llm_bind_tools`) para poder consultar y escribir en la base de datos de incidentes pasados.

**Contexto que recibe del estado:**

| Campo | Fuente |
|---|---|
| `messages[-1].content` | Descripción original del usuario |
| `category` | Salida del `classifier_agent` |
| `priority` | Salida del `classifier_agent` |

**Herramientas disponibles:**

| Herramienta | Descripción |
|---|---|
| `search_incident_by_category` | Consulta PostgreSQL buscando incidentes similares por categoría |
| `insert_incident` | Almacena el nuevo incidente en la base de datos |

**Campos retornados:**

| Campo | Tipo | Descripción |
|---|---|---|
| `messages` | `list` | Lista con la respuesta del LLM (habilita el nodo de tools) |
| `recommendations` | `str` | Contenido textual de las recomendaciones generadas |
| `current_step` | `str` | Siempre `"recommendation_done"` |

### Relación con otros agentes

```
Orchestrator Agent
      │
      │ (next_agent = "recommendation")
      ▼
Recommendation Agent  ──── tool_calls ────▶  Tools Node (PostgreSQL)
      │                                             │
      │◀────────────────── tool results ────────────┘
      │
      ▼
    END
```

- **Precedido por:** `orchestrator_agent` (segunda ejecución) que lo activa tras `"classifier_done"`.
- **Consume directamente** los campos `category` y `priority` generados por `classifier_agent`.
- **Interactúa con la base de datos** a través del nodo de herramientas de LangGraph, no directamente.
- Es el **último agente activo** del grafo antes de terminar.

### Posibles errores

| Error | Causa | Comportamiento |
|---|---|---|
| `ValueError("Ocurrió un error en el agente de recomendación.")` | Cualquier excepción interna | Capturada con `except Exception`, registrada y relanzada |
| `KeyError` | Si `state["category"]` o `state["priority"]` no existen (el clasificador no se ejecutó antes) | Provoca el `ValueError` anterior |
| `FileNotFoundError` | Si `prompt/recomendation_agent.md` no existe | Provoca el `ValueError` anterior |
| Error de conexión a base de datos | Si PostgreSQL no está disponible cuando se invocan las herramientas | La herramienta falla, el LLM recibe un error como resultado de tool |
| Recomendaciones vacías | Si el LLM retorna contenido vacío (`response.content = ""`) | El campo `recommendations` queda vacío sin lanzar error |

### Pruebas realizadas

**Archivo:** [tests/unit/test_recommendation.py](../tests/unit/test_recommendation.py)  
**Total: 6 pruebas — todas PASSED**

| # | Nombre del test | Qué verifica | Resultado |
|---|---|---|---|
| 1 | `test_returns_messages_and_recommendations` | Que la respuesta contiene `messages`, `recommendations` y `current_step` | PASSED |
| 2 | `test_recommendations_content_matches_llm_response` | Que `recommendations` es exactamente el contenido de la respuesta del LLM | PASSED |
| 3 | `test_sets_current_step_to_recommendation_done` | Que `current_step` siempre es `"recommendation_done"` | PASSED |
| 4 | `test_messages_list_contains_llm_response` | Que `messages` contiene exactamente el `AIMessage` retornado por el LLM | PASSED |
| 5 | `test_uses_category_and_priority_from_state` | Que el contexto enviado al LLM incluye `category` y `priority` del estado | PASSED |
| 6 | `test_raises_value_error_on_llm_failure` | Que lanza `ValueError` cuando el LLM falla | PASSED |

**Estrategia de prueba:** Se mockea `agents.recomendation_agent.llm_bind_tools` para simular respuestas del LLM con herramientas sin llamadas reales a la API ni a la base de datos.

---

## Pruebas de Integración (flujo completo)

**Archivo:** [tests/integration/test_full_flow.py](../tests/integration/test_full_flow.py)  
**Total: 4 pruebas — todas PASSED**

Estas pruebas ejecutan el grafo completo de LangGraph con todos los agentes mockeados, verificando que la orquestación funciona correctamente de extremo a extremo.

| # | Nombre del test | Qué verifica | Resultado |
|---|---|---|---|
| 1 | `test_complete_workflow_state_after_execution` | Que el estado final tiene todos los campos correctamente poblados tras el flujo completo | PASSED |
| 2 | `test_each_agent_is_called_correct_number_of_times` | Que el orchestrator se llama 2 veces, el classifier 1 vez y recommendation 1 vez | PASSED |
| 3 | `test_orchestrator_shortcuts_to_end` | Que si el orchestrator decide `"end"` directamente, classifier y recommendation no se invocan | PASSED |
| 4 | `test_database_tool_is_called_with_correct_category` | Que la herramienta de base de datos recibe el parámetro `category` correcto | PASSED |

---

## Resumen General

| Agente | Tests unitarios | Tests integración | Estado |
|---|---|---|---|
| `classifier_agent` | 7/7 | Cubierto en los 4 tests de integración | ✅ Todo OK |
| `orchestrator_agent` | 6/6 | Cubierto en los 4 tests de integración | ✅ Todo OK |
| `recomendation_agent` | 6/6 | Cubierto en los 4 tests de integración | ✅ Todo OK |
| **Total** | **19/19** | **4/4** | **23/23 PASSED** |

### Advertencias detectadas (no bloqueantes)

1. **`LangChainPendingDeprecationWarning`** en `langgraph/cache/base/__init__.py:8` — El valor por defecto de `allowed_objects` cambiará en una versión futura. Acción recomendada: pasar `allowed_objects='messages'` o `allowed_objects='core'` explícitamente.

2. **`UserWarning`** en `langchain_openai/chat_models/base.py:2381` — El modelo `gpt-4` no soporta la API de Structured Outputs con `method='json_schema'`. LangChain lo sobreescribe automáticamente a `method='function_calling'`. Acción recomendada: cambiar el modelo a `gpt-4o` o superior, o configurar explícitamente `method='function_calling'` en los modelos que usan salida estructurada.
