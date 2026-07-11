"""
Script de evaluación de precisión y calidad para AI Incident Response System.

Corre los 20 casos de `eval_dataset.json` contra la API en vivo (POST /incident)
y calcula dos capas de métricas:

1. Precisión "dura" del Classifier Agent (comparación exacta/objetiva contra
   ground truth): acierto de categoría, acierto de prioridad y cobertura de
   causas clave esperadas.

2. Calidad "blanda" de las recomendaciones del Recommendation Agent, evaluada
   por un LLM-judge (modelo distinto al que usa el agente, para reducir sesgo
   de auto-evaluación) sobre 4 dimensiones: relevancia, accionabilidad,
   fundamentación y completitud (escala 1-5 cada una).

Requisitos previos:
    - El servidor debe estar corriendo (`uvicorn main:app --reload`).
    - OPENAI_API_KEY configurado en el .env del proyecto (se usa para el LLM-judge;
      si no está disponible, se puede correr solo con --skip-judge).

Uso:
    python evaluation/run_eval.py
    python evaluation/run_eval.py --skip-judge
    python evaluation/run_eval.py --base-url http://127.0.0.1:8000 --limit 5

Salida (en evaluation/results/):
    - eval_results.csv   → una fila por caso con todas las métricas
    - eval_report.md      → resumen agregado legible
"""

import argparse
import csv
import json
import os
import sys
import time
import unicodedata
from pathlib import Path

import requests
from dotenv import load_dotenv
from loguru import logger

# ─── Config ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
DEFAULT_DATASET = BASE_DIR / "eval_dataset.json"
DEFAULT_OUT_DIR = BASE_DIR / "results"

CAUSES_COVERAGE_THRESHOLD = 0.5  # % mínimo de keywords esperadas para considerar "cubierto"

JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "gpt-4o")  # modelo distinto al del agente (gpt-4o-mini)

JUDGE_SYSTEM_PROMPT = """Eres un evaluador experto e imparcial de calidad de recomendaciones técnicas \
para incidentes de TI. Vas a recibir la descripción de un incidente, su clasificación \
(categoría y prioridad) y las recomendaciones generadas por un agente de IA. Tu trabajo es \
puntuar esas recomendaciones, NO generar nuevas recomendaciones.

Evalúa en 4 dimensiones, cada una en escala de 1 (muy deficiente) a 5 (excelente):

- relevancia: ¿las recomendaciones abordan específicamente el incidente reportado, o son genéricas?
- accionabilidad: ¿son pasos concretos y ejecutables por un equipo técnico, o son vagas?
- fundamentacion: ¿el diagnóstico/causas parecen coherentes y respaldadas (documentación, casos \
similares, o buen criterio técnico), en vez de inventadas?
- completitud: ¿cubre diagnóstico Y recomendaciones de forma completa, sin dejar huecos obvios?

Responde ÚNICAMENTE con un JSON válido con este formato exacto, sin texto adicional:
{"relevancia": <int>, "accionabilidad": <int>, "fundamentacion": <int>, "completitud": <int>, "comentario": "<una frase breve justificando la puntuación>"}
"""


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Minúsculas y sin acentos, para comparaciones tolerantes."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def call_incident_api(base_url: str, user_input: str, timeout: int = 120) -> dict:
    """
    Llama a POST /incident. Deliberadamente NO reutiliza cookies entre llamadas
    (cada invocación usa una request nueva sin sesión previa), de modo que cada
    caso del dataset arranca una conversación nueva y aislada en el grafo.
    """
    resp = requests.post(
        f"{base_url}/incident",
        json={"user_input": user_input},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def score_hard_metrics(case: dict, api_response: dict) -> dict:
    got_category = api_response.get("category") or ""
    got_priority = api_response.get("priority") or ""
    got_causes = api_response.get("possible_causes") or []
    causes_text = _normalize(" ".join(got_causes) if isinstance(got_causes, list) else str(got_causes))

    category_match = _normalize(got_category) == _normalize(case["expected_category"])
    priority_match = _normalize(got_priority) == _normalize(case["expected_priority"])

    expected_keywords = case.get("expected_causes_keywords", [])
    hits = [kw for kw in expected_keywords if _normalize(kw) in causes_text]
    causes_score = (len(hits) / len(expected_keywords)) if expected_keywords else None

    return {
        "got_category": got_category,
        "got_priority": got_priority,
        "category_match": category_match,
        "priority_match": priority_match,
        "causes_score": causes_score,
        "causes_hits": ", ".join(hits) if hits else "",
        "causes_missing": ", ".join(kw for kw in expected_keywords if kw not in hits),
    }


def judge_recommendations(client, incident_desc: str, category: str, priority: str, recommendations: str) -> dict:
    """Usa un LLM (modelo distinto al del agente) para puntuar la calidad de las recomendaciones."""
    if not recommendations:
        return {"relevancia": None, "accionabilidad": None, "fundamentacion": None, "completitud": None, "comentario": "Sin recomendaciones generadas."}

    user_content = f"""Incidente reportado:
{incident_desc}

Clasificación del agente:
- Categoría: {category}
- Prioridad: {priority}

Recomendaciones generadas por el agente:
{recommendations}
"""
    try:
        response = client.chat.completions.create(
            model=JUDGE_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        raw = response.choices[0].message.content
        parsed = json.loads(raw)
        return parsed
    except Exception as e:
        logger.error(f"[JUDGE] Error evaluando recomendaciones: {e}")
        return {"relevancia": None, "accionabilidad": None, "fundamentacion": None, "completitud": None, "comentario": f"Error del judge: {e}"}


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Evalúa precisión y calidad del agente de incidentes.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Ruta al JSON del dataset.")
    parser.add_argument("--base-url", default=os.getenv("EVAL_BASE_URL", "http://127.0.0.1:8000"), help="URL base de la API.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Carpeta de salida para los reportes.")
    parser.add_argument("--limit", type=int, default=None, help="Solo correr los primeros N casos (para pruebas rápidas).")
    parser.add_argument("--skip-judge", action="store_true", help="Omite la evaluación de calidad vía LLM-judge (solo métricas duras).")
    parser.add_argument("--delay", type=float, default=1.0, help="Segundos de espera entre requests (para no saturar la API/OpenAI).")
    args = parser.parse_args()

    load_dotenv(override=True)

    dataset_path = Path(args.dataset)
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    cases = dataset["cases"]
    if args.limit:
        cases = cases[: args.limit]

    judge_client = None
    if not args.skip_judge:
        try:
            from openai import OpenAI
            if not os.getenv("OPENAI_API_KEY"):
                logger.warning("OPENAI_API_KEY no configurada. Se omite el LLM-judge (usa --skip-judge para silenciar este aviso).")
            else:
                judge_client = OpenAI()
        except ImportError:
            logger.warning("Paquete 'openai' no disponible. Se omite el LLM-judge.")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    logger.info(f"Corriendo evaluación | casos={len(cases)} | base_url={args.base_url} | judge={'on' if judge_client else 'off'}")

    for i, case in enumerate(cases, 1):
        logger.info(f"[{i}/{len(cases)}] {case['id']} — {case['user_input'][:70]}...")
        row = {"id": case["id"], "expected_category": case["expected_category"], "expected_priority": case["expected_priority"]}

        try:
            api_response = call_incident_api(args.base_url, case["user_input"])
        except Exception as e:
            logger.error(f"  Error llamando a la API: {e}")
            row.update({"error": str(e)})
            results.append(row)
            continue

        hard = score_hard_metrics(case, api_response)
        row.update(hard)
        row["recommendations"] = api_response.get("recommendations") or ""

        if judge_client:
            judge_scores = judge_recommendations(
                judge_client,
                case["user_input"],
                api_response.get("category", ""),
                api_response.get("priority", ""),
                row["recommendations"],
            )
            row.update({f"judge_{k}": v for k, v in judge_scores.items()})

        results.append(row)
        time.sleep(args.delay)

    _write_csv(out_dir / "eval_results.csv", results)
    _write_report(out_dir / "eval_report.md", results, args)
    logger.info(f"Listo. Resultados en: {out_dir}")


def _write_csv(path: Path, results: list) -> None:
    fieldnames = sorted({k for row in results for k in row.keys()})
    # Orden preferido de columnas al frente
    preferred = ["id", "expected_category", "got_category", "category_match",
                 "expected_priority", "got_priority", "priority_match",
                 "causes_score", "causes_hits", "causes_missing",
                 "judge_relevancia", "judge_accionabilidad", "judge_fundamentacion",
                 "judge_completitud", "judge_comentario", "recommendations", "error"]
    ordered = [c for c in preferred if c in fieldnames] + [c for c in fieldnames if c not in preferred]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ordered)
        writer.writeheader()
        for row in results:
            writer.writerow(row)


def _write_report(path: Path, results: list, args) -> None:
    valid = [r for r in results if "error" not in r]
    n = len(valid)
    errors = len(results) - n

    def pct(count):
        return f"{(count / n * 100):.1f}%" if n else "N/A"

    category_hits = sum(1 for r in valid if r.get("category_match"))
    priority_hits = sum(1 for r in valid if r.get("priority_match"))
    causes_scores = [r["causes_score"] for r in valid if r.get("causes_score") is not None]
    avg_causes = (sum(causes_scores) / len(causes_scores)) if causes_scores else None
    causes_ok = sum(1 for s in causes_scores if s >= CAUSES_COVERAGE_THRESHOLD)

    judge_dims = ["relevancia", "accionabilidad", "fundamentacion", "completitud"]
    judge_avgs = {}
    for dim in judge_dims:
        vals = [r.get(f"judge_{dim}") for r in valid if isinstance(r.get(f"judge_{dim}"), (int, float))]
        judge_avgs[dim] = (sum(vals) / len(vals)) if vals else None

    # Breakdown por categoría
    by_category = {}
    for r in valid:
        cat = r["expected_category"]
        by_category.setdefault(cat, {"total": 0, "cat_ok": 0, "prio_ok": 0})
        by_category[cat]["total"] += 1
        if r.get("category_match"):
            by_category[cat]["cat_ok"] += 1
        if r.get("priority_match"):
            by_category[cat]["prio_ok"] += 1

    lines = []
    lines.append("# Reporte de Evaluación — AI Incident Response System\n")
    lines.append(f"Generado: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Casos evaluados: {len(results)} (válidos: {n}, con error de API: {errors})")
    lines.append(f"Judge: {'activo (' + JUDGE_MODEL + ')' if any('judge_relevancia' in r for r in valid) else 'omitido'}\n")

    lines.append("## Métricas duras — Classifier Agent\n")
    lines.append(f"- Acierto de categoría: **{category_hits}/{n} ({pct(category_hits)})**")
    lines.append(f"- Acierto de prioridad: **{priority_hits}/{n} ({pct(priority_hits)})**")
    if avg_causes is not None:
        lines.append(f"- Cobertura promedio de causas clave esperadas: **{avg_causes * 100:.1f}%**")
        lines.append(f"- Casos con cobertura de causas >= {int(CAUSES_COVERAGE_THRESHOLD*100)}%: **{causes_ok}/{len(causes_scores)}**")
    lines.append("")

    lines.append("### Desglose por categoría\n")
    lines.append("| Categoría | Casos | Acierto categoría | Acierto prioridad |")
    lines.append("|---|---|---|---|")
    for cat, d in by_category.items():
        lines.append(f"| {cat} | {d['total']} | {d['cat_ok']}/{d['total']} | {d['prio_ok']}/{d['total']} |")
    lines.append("")

    if any(v is not None for v in judge_avgs.values()):
        lines.append("## Métricas de calidad — Recommendation Agent (LLM-judge, escala 1-5)\n")
        for dim, avg in judge_avgs.items():
            lines.append(f"- {dim.capitalize()}: **{avg:.2f}/5**" if avg is not None else f"- {dim.capitalize()}: N/A")
        overall = [v for v in judge_avgs.values() if v is not None]
        if overall:
            lines.append(f"- **Promedio general: {sum(overall)/len(overall):.2f}/5**")
        lines.append("")

    lines.append("## Casos con fallas (revisar manualmente)\n")
    fails = [r for r in valid if not r.get("category_match") or not r.get("priority_match") or (r.get("causes_score") is not None and r["causes_score"] < CAUSES_COVERAGE_THRESHOLD)]
    if fails:
        for r in fails:
            lines.append(f"- **{r['id']}**: esperado categoría={r['expected_category']}/prioridad={r['expected_priority']} → obtenido categoría={r.get('got_category')}/prioridad={r.get('got_priority')}, cobertura_causas={r.get('causes_score')}")
    else:
        lines.append("Ninguno — todos los casos cumplieron los umbrales mínimos.")
    lines.append("")

    if errors:
        lines.append("## Casos con error de API\n")
        for r in results:
            if "error" in r:
                lines.append(f"- **{r['id']}**: {r['error']}")
        lines.append("")

    lines.append("---")
    lines.append(f"Ver detalle completo por caso en `eval_results.csv` (mismo directorio).")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
