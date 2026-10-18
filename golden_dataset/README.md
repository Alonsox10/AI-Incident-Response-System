# Golden dataset

30 incidentes con ground truth de **categoría** y **prioridad**, 6 por cada categoría soportada. Es el set de regresión estable del clasificador: si un cambio de prompt, de modelo o de schema mueve estos números, hay una regresión.

```bash
python golden_dataset/run_golden.py                        # los 30 casos
python golden_dataset/run_golden.py --limit 5              # prueba rápida
python golden_dataset/run_golden.py --solo-categoria Redes # una categoría
```

En Windows sin el venv activado: `./venv/Scripts/python.exe golden_dataset/run_golden.py`.

**No necesita el servidor ni Postgres levantados** — el clasificador no toca la base. Solo requiere `OPENAI_API_KEY` en el `.env`. Por eso sirve para verificar en cualquier momento, incluso con el entorno a medio levantar. Sale con código 1 si hay algún fallo, así que se puede encadenar en CI.

## Cómo encaja con las otras evaluaciones

| | Qué mide | Necesita |
|---|---|---|
| `pytest` | Lógica de los agentes, con todo mockeado | Nada |
| `golden_dataset/run_golden.py` | **Clasificación real** contra ground truth | `OPENAI_API_KEY` |
| `evaluation/run_flow_eval.py` | Recorrido del grafo: routing, tools, RAG, ramas | Postgres + `seed.py` |
| `evaluation/run_eval.py` | Calidad redaccional de las recomendaciones (LLM-judge) | Servidor `uvicorn` |

**"Hacer test" en este proyecto son las dos primeras filas**: `pytest` + este golden dataset. Las de `evaluation/` se corren cuando el cambio toca prompts, umbrales o el modelo.

Existe porque la evaluación de flujo solo cubría **4 casos** de clasificación: un 100% sobre esa base era una anécdota, no una medición.

## Qué contiene

6 casos por categoría (Error backend, Error frontend, Infraestructura, Redes, Seguridad), repartidos entre las tres prioridades. Los casos no son aleatorios: incluyen a propósito los pares que el prompt marca como confundibles.

- **GD-16** (CPU al 95% en cierre de mes, sin cambios de código) vs **GD-01** (error 500 tras un deploy) — separa Infraestructura de Error backend por la señal que da el prompt: si correlaciona con volumen es capacidad; si correlaciona con un evento de código es bug.
- **GD-19** (una sucursal pierde todos los sistemas mientras el resto opera normal) — separa Redes de Infraestructura.
- **GD-28** (CVE crítico sin explotación) vs **GD-25** (ransomware cifrando ahora) — separa Media de Alta en seguridad.

## Línea base — 2026-10-17

| Métrica | Resultado |
|---|---|
| Categoría correcta | **100%** (30/30) |
| Prioridad correcta | **86.7%** (26/30) |
| Ambas correctas | **86.7%** (26/30) |

Acierto de categoría perfecto en las cinco categorías, incluidos los casos trampa. Cifra estable desde el 2026-09-28.

### Sesgo detectado: la frontera Baja/Media

Los **4 fallos son el mismo patrón**: casos marcados como `Baja` que el clasificador eleva a `Media` (GD-06, GD-18, GD-24, GD-30). Nunca al revés, y nunca falla entre Media y Alta.

La causa está en `prompt/classify_agent.md`: los criterios se solapan. Media dice *"afecta a un subconjunto de usuarios"* y Baja dice *"afecta a muy pocos usuarios"* — GD-24 (un solo equipo sin IP) cumple literalmente los dos, así que la instrucción "no eleves la prioridad por si acaso" no alcanza para desempatar. Agrava el problema que el único ejemplo de `Baja` del prompt sea cosmético (estilos CSS): el modelo no tiene de dónde inferir que un fallo funcional que afecta a una sola persona también es `Baja`.

De los cuatro, **GD-24 es el más claro** (un equipo de una sala, con el resto funcionando, no es "un subconjunto"), y GD-06 y GD-18 son genuinamente discutibles.

> El ground truth **no se ajustó** para que coincidiera con el modelo. Un golden set que se reescribe cuando el sistema falla deja de ser una referencia. Si al revisarlos se concluye que la expectativa estaba mal, se corrige el caso y se anota por qué; si estaba bien, se corrige el prompt.

Corregirlo es la tarea 3 de la Fase 3 de `PLAN_PRODUCCION.md`. Objetivo: ≥95% en prioridad sin mover el 100% de categoría.

## Mantenerlo

- Cambiar un caso existente es una decisión deliberada, no un ajuste para que dé verde. Al hacerlo, actualizar la `nota` explicando el criterio.
- Al agregar una categoría o un nivel de prioridad nuevo, sumar casos: si no, el golden set se queda ciego justo donde el sistema creció.
- La taxonomía válida vive en `schemas/models.py` (`IncidentCategory`, `IncidentPriority`) y está declarada también en el bloque `taxonomia` de `incidents.json`. Cambiarla exige tocar los tres sitios a la vez: schema, `prompt/classify_agent.md` y este dataset.
