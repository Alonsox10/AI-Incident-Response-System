# Evaluación del agente

Dos evaluaciones complementarias, que miden cosas distintas:

| Script | Qué mide | Cómo corre |
|---|---|---|
| `run_eval.py` | **Contenido**: precisión del clasificador y calidad de las recomendaciones | Contra la API HTTP (requiere `uvicorn` levantado) |
| `run_flow_eval.py` | **Flujo**: qué agente atendió, qué tools se invocaron, si el RAG trajo contexto, qué rama tomó FAQ | En proceso, importando el grafo |

Una respuesta puede ser excelente y aun así haber recorrido el grafo mal (por ejemplo, clasificar como incidente una pregunta de procedimiento: la respuesta sale bien, pero cuesta 3× y registra un incidente falso). Por eso hacen falta las dos.

> Para la regresión del **clasificador** hay además un golden dataset aparte, en `golden_dataset/` — 30 incidentes con ground truth, sin necesidad de Postgres ni servidor. Junto con `pytest`, es lo que compone "hacer test" en este proyecto; estas dos de acá se corren cuando el cambio toca prompts, umbrales o el modelo.

---

## Evaluación de flujo (`run_flow_eval.py`)

```bash
python evaluation/run_flow_eval.py             # los 20 casos de flow_dataset.json
python evaluation/run_flow_eval.py --limit 3   # prueba rápida
```

No necesita el servidor levantado, pero sí Postgres corriendo y las tablas pobladas (`python seed.py`).

Envuelve el pre-chequeo del orquestador, la búsqueda de FAQs y las dos funciones de RAG para **observar** el recorrido en vez de inferirlo desde la respuesta final. Checks por caso: `routing`, `paso_final`, `tools`, `sin_tools`, `rag`, `rag_diversidad`, `faq_branch`, `clasificacion` — cada uno se evalúa solo si el caso lo declara.

> `rag_diversidad` compara el **hash del contenido** de los documentos recuperados, no sus ids. Existe porque la base llegó a tener 20 filas con solo 10 contenidos distintos (el mismo PDF ingestado dos veces): cada búsqueda devolvía documentos repetidos y todas las demás métricas seguían en verde.

### Línea base — 2026-09-28

| Agente | Efectividad | n |
|---|---|---|
| Orquestador (routing) | 100% | 20 |
| Clasificador (categoría) | 100% | 4 |
| Recomendación (tools) | 100% | 10 |
| RAG (contexto esperado) | 100% | 10 |
| RAG (sin duplicados) | 100% | 8 |
| Agente de FAQ (rama) | 100% | 9 |
| **Casos sin ningún fallo** | **100%** | 20/20 |

Latencia media: **3.0 s** por FAQ contra **10.2 s** por el camino de incidente (~1.4 s cuando resuelve el pre-chequeo determinístico sin tocar el LLM).

Correr este script antes y después de cada cambio de prompt, de umbral o de modelo. Un 100% no significa que el sistema sea perfecto: significa que no hay regresiones respecto de lo que este dataset sabe mirar. Al agregar una capacidad nueva, agregarle casos — si no, la línea base se queda ciega justo donde el sistema creció.

---

## Evaluación de contenido (`run_eval.py`)

### Archivos

- `eval_dataset.json` — 20 casos sintéticos (4 por categoría: Error backend, Error frontend, Infraestructura, Redes, Seguridad), cada uno con el ground truth esperado (`expected_category`, `expected_priority`, `expected_causes_keywords`).
- `run_eval.py` — corre cada caso contra `POST /incident` y calcula métricas.
- `results/` — se genera al correr el script (no versionar en git si el repo es público, puede contener texto de incidentes reales si se reemplaza el dataset).

### Qué mide

**Métricas duras (objetivas)** — comparación exacta contra el ground truth del dataset:
- Acierto de `category`
- Acierto de `priority`
- % de cobertura de las palabras clave esperadas dentro de `possible_causes`

**Métricas de calidad (LLM-judge)** — un modelo distinto al del agente (`gpt-4o` por defecto, configurable con `EVAL_JUDGE_MODEL`) puntúa las `recommendations` generadas en 4 dimensiones (escala 1-5): relevancia, accionabilidad, fundamentación y completitud. Usar un modelo distinto al del agente (`gpt-4o-mini`) reduce el sesgo de que el modelo se autoevalúe favorablemente.

### Cómo correrlo

1. Levanta el servidor: `uvicorn main:app --reload`
2. Asegúrate de tener `OPENAI_API_KEY` en tu `.env` (se usa tanto para el agente como para el judge).
3. Desde la raíz del proyecto:

```bash
python evaluation/run_eval.py
```

Opciones útiles:

```bash
# Prueba rápida con solo 3 casos
python evaluation/run_eval.py --limit 3

# Sin LLM-judge (solo métricas duras, más rápido y sin costo de API extra)
python evaluation/run_eval.py --skip-judge

# Contra otra URL (ej. Docker)
python evaluation/run_eval.py --base-url http://localhost:8000
```

### Salida

- `results/eval_results.csv` — una fila por caso con todos los valores esperados/obtenidos y scores.
- `results/eval_report.md` — resumen agregado: % de acierto global, desglose por categoría, promedios del judge y lista de casos que fallaron para revisión manual.

### Notas

- Cada caso arranca una conversación nueva y aislada: el script no reutiliza cookies entre llamadas, así que cada request crea su propia sesión en el grafo (no hay contaminación entre casos).
- El umbral de "cobertura de causas aceptable" es 50% (configurable en `CAUSES_COVERAGE_THRESHOLD` dentro de `run_eval.py`).
- Este dataset es sintético. Si el equipo empieza a acumular incidentes reales (y sus clasificaciones correctas confirmadas por un humano), lo ideal es ir reemplazando o ampliando `eval_dataset.json` con esos casos reales — dan una medida de precisión mucho más representativa que los sintéticos.
- Si el % de acierto de categoría/prioridad baja notablemente después de un cambio de prompt o de modelo, correr este script antes/después del cambio permite detectar regresiones antes de desplegar.
