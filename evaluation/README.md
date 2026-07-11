# Evaluación del agente

Dataset y script para medir precisión (Classifier Agent) y calidad (Recommendation Agent) de forma repetible.

## Contenido

- `eval_dataset.json` — 20 casos sintéticos (4 por categoría: Error backend, Error frontend, Infraestructura, Redes, Seguridad), cada uno con el ground truth esperado (`expected_category`, `expected_priority`, `expected_causes_keywords`).
- `run_eval.py` — corre cada caso contra `POST /incident` y calcula métricas.
- `results/` — se genera al correr el script (no versionar en git si el repo es público, puede contener texto de incidentes reales si se reemplaza el dataset).

## Qué mide

**Métricas duras (objetivas)** — comparación exacta contra el ground truth del dataset:
- Acierto de `category`
- Acierto de `priority`
- % de cobertura de las palabras clave esperadas dentro de `possible_causes`

**Métricas de calidad (LLM-judge)** — un modelo distinto al del agente (`gpt-4o` por defecto, configurable con `EVAL_JUDGE_MODEL`) puntúa las `recommendations` generadas en 4 dimensiones (escala 1-5): relevancia, accionabilidad, fundamentación y completitud. Usar un modelo distinto al del agente (`gpt-4o-mini`) reduce el sesgo de que el modelo se autoevalúe favorablemente.

## Cómo correrlo

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

## Salida

- `results/eval_results.csv` — una fila por caso con todos los valores esperados/obtenidos y scores.
- `results/eval_report.md` — resumen agregado: % de acierto global, desglose por categoría, promedios del judge y lista de casos que fallaron para revisión manual.

## Notas

- Cada caso arranca una conversación nueva y aislada: el script no reutiliza cookies entre llamadas, así que cada request crea su propia sesión en el grafo (no hay contaminación entre casos).
- El umbral de "cobertura de causas aceptable" es 50% (configurable en `CAUSES_COVERAGE_THRESHOLD` dentro de `run_eval.py`).
- Este dataset es sintético. Si el equipo empieza a acumular incidentes reales (y sus clasificaciones correctas confirmadas por un humano), lo ideal es ir reemplazando o ampliando `eval_dataset.json` con esos casos reales — dan una medida de precisión mucho más representativa que los sintéticos.
- Si el % de acierto de categoría/prioridad baja notablemente después de un cambio de prompt o de modelo, correr este script antes/después del cambio permite detectar regresiones antes de desplegar.
