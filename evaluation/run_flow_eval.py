"""
Evaluación de FLUJO del sistema multiagente.

Complementa a run_eval.py: aquel mide la calidad del contenido de las respuestas
(precisión del clasificador + LLM-judge); este mide que el grafo se recorra como
fue diseñado — qué agente atendió cada consulta, qué tools se invocaron, si el RAG
devolvió contexto y qué rama tomó el agente de FAQ.

A diferencia de run_eval.py, NO pega a la API HTTP: importa el grafo y lo invoca
en proceso, envolviendo las funciones clave para observar el recorrido real en vez
de inferirlo desde la respuesta final.

Uso:
    python evaluation/run_flow_eval.py
    python evaluation/run_flow_eval.py --limit 3
"""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)

import uuid
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

BASE_DIR = Path(__file__).parent
DEFAULT_DATASET = BASE_DIR / "flow_dataset.json"
DEFAULT_OUT_DIR = BASE_DIR / "results"


# ─── Instrumentación ──────────────────────────────────────────────────────────

class Traza:
    """Acumula lo observado durante la ejecución de un caso."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.prechequeo_similitud = None
        self.faq_top_similitud = None
        self.faq_resultados = None
        self.rag_kb_resultados = None
        self.rag_hist_resultados = None
        # Similitudes crudas (sin umbral) para poder calibrar dónde cortar
        self.rag_kb_sims = None
        self.rag_kb_hashes = None
        self.nodos = []


TRAZA = Traza()


def instrumentar():
    """
    Envuelve las funciones clave del grafo para registrar el recorrido real.
    Cada wrapper delega en la función original: no altera el comportamiento.
    """
    import agents.orchestrator_agent as orch
    import agents.faq_agent as faq
    import tools.rag_tools as rag

    _orig_prechequeo = orch._coincide_con_faq_documentada
    _orig_faq_search = faq.search_faqs
    _orig_kb = rag.search_knowledge_base
    _orig_hist = rag.search_similar_incidents

    def prechequeo(user_input):
        r = _orig_prechequeo(user_input)
        TRAZA.prechequeo_similitud = r
        return r

    def faq_search(embedding, top_k=3, **kw):
        r = _orig_faq_search(embedding, top_k=top_k, **kw)
        TRAZA.faq_resultados = len(r)
        TRAZA.faq_top_similitud = r[0]["similarity"] if r else None
        return r

    def kb(embedding, top_k=4, **kw):
        r = _orig_kb(embedding, top_k=top_k, **kw)
        TRAZA.rag_kb_resultados = len(r)
        # Huella del contenido, no del id: los duplicados que tuvo esta base eran filas
        # distintas con texto idéntico, así que comparar ids no los habría detectado.
        TRAZA.rag_kb_hashes = [hashlib.sha1(x["content"].encode("utf-8")).hexdigest()[:12] for x in r]
        # Diagnóstico: el mismo embedding sin umbral, para ver la distribución real.
        # No cuesta una llamada de embeddings extra, solo una query vectorial.
        crudo = _orig_kb(embedding, top_k=6, similarity_threshold=0.0)
        TRAZA.rag_kb_sims = [round(x["similarity"], 3) for x in crudo]
        return r

    def hist(embedding, top_k=3, **kw):
        r = _orig_hist(embedding, top_k=top_k, **kw)
        TRAZA.rag_hist_resultados = len(r)
        return r

    orch._coincide_con_faq_documentada = prechequeo
    faq.search_faqs = faq_search
    rag.search_knowledge_base = kb
    rag.search_similar_incidents = hist


# ─── Ejecución de un caso ─────────────────────────────────────────────────────

def ejecutar_caso(app, case: dict) -> dict:
    """Corre un caso por el grafo completo y devuelve lo observado."""
    from agents.faq_agent import FAQ_HIGH_CONFIDENCE_THRESHOLD

    TRAZA.reset()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    input_state = {
        "messages": [HumanMessage(content=case["user_input"])],
        "category": None,
        "priority": None,
        "possible_causes": None,
        "recommendations": None,
        "current_step": None,
    }

    inicio = time.perf_counter()
    estado_final = {}
    error = None
    try:
        for update in app.stream(input_state, config=config, stream_mode="updates"):
            for nodo, delta in update.items():
                TRAZA.nodos.append(nodo)
                if isinstance(delta, dict):
                    estado_final.update(delta)
    except Exception as e:
        error = str(e)
    duracion = time.perf_counter() - inicio

    # El agente que efectivamente atendió la consulta
    ruta = "faq" if "faq" in TRAZA.nodos else ("classifier" if "classifier" in TRAZA.nodos else "end")

    # Rama del agente de FAQ, derivada de lo observado en la búsqueda
    faq_branch = None
    if "faq" in TRAZA.nodos:
        if not TRAZA.faq_resultados:
            faq_branch = "sin_resultados"
        elif TRAZA.faq_top_similitud >= FAQ_HIGH_CONFIDENCE_THRESHOLD:
            faq_branch = "alta_confianza"
        else:
            faq_branch = "baja_confianza"

    # Tools solicitadas por el agente de recomendación
    tools_llamadas = []
    mensajes = app.get_state(config).values.get("messages", [])
    for m in mensajes:
        if isinstance(m, AIMessage) and m.tool_calls:
            tools_llamadas.extend(tc["name"] for tc in m.tool_calls)

    return {
        "ruta": ruta,
        "nodos": TRAZA.nodos,
        "prechequeo_disparo": TRAZA.prechequeo_similitud is not None,
        "prechequeo_similitud": TRAZA.prechequeo_similitud,
        "faq_branch": faq_branch,
        "faq_top_similitud": TRAZA.faq_top_similitud,
        "tools_llamadas": sorted(set(tools_llamadas)),
        "rag_kb_resultados": TRAZA.rag_kb_resultados,
        "rag_kb_sims": TRAZA.rag_kb_sims,
        "rag_kb_hashes": TRAZA.rag_kb_hashes,
        "rag_hist_resultados": TRAZA.rag_hist_resultados,
        "category": estado_final.get("category"),
        "priority": estado_final.get("priority"),
        "current_step": estado_final.get("current_step"),
        "respuesta": estado_final.get("recommendations") or "",
        "duracion_s": round(duracion, 2),
        "error": error,
    }


# ─── Scoring ──────────────────────────────────────────────────────────────────

def evaluar(case: dict, obs: dict) -> dict:
    """Compara lo observado contra lo esperado. Cada check se evalúa solo si el caso lo declara."""
    checks = {}

    checks["routing"] = obs["ruta"] == case["expected_route"]

    if case.get("expected_faq_branch"):
        checks["faq_branch"] = obs["faq_branch"] == case["expected_faq_branch"]

    if case.get("expected_current_step"):
        checks["paso_final"] = obs["current_step"] == case["expected_current_step"]

    if case.get("expected_tools"):
        esperadas = set(case["expected_tools"])
        checks["tools"] = esperadas.issubset(set(obs["tools_llamadas"]))

    if case.get("expected_no_tools"):
        # Un reporte sin síntoma accionable no debe registrar incidente ni consultar el RAG
        checks["sin_tools"] = obs["tools_llamadas"] == []

    if case.get("expected_rag_hit") is not None:
        hubo_contexto = bool(obs["rag_kb_resultados"]) or bool(obs["rag_hist_resultados"])
        # Solo es evaluable si el caso llegó al agente de recomendación
        if obs["ruta"] == "classifier":
            checks["rag"] = hubo_contexto == case["expected_rag_hit"]

    if case.get("expected_category"):
        checks["clasificacion"] = obs["category"] == case["expected_category"]

    # Diversidad de la recuperación: los documentos devueltos deben ser distintos entre sí.
    # Sin este check, una base con contenido duplicado puntúa igual que una sana —
    # fue exactamente lo que pasó: 20 filas con solo 10 contenidos, y el marcador en verde.
    if obs["rag_kb_hashes"]:
        checks["rag_diversidad"] = len(set(obs["rag_kb_hashes"])) == len(obs["rag_kb_hashes"])

    return checks


def porcentaje(aciertos: int, total: int) -> float:
    return round(100 * aciertos / total, 1) if total else 0.0


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Evalúa el flujo del grafo multiagente.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    casos = dataset["cases"][: args.limit] if args.limit else dataset["cases"]

    instrumentar()
    from graphs.incidente_graph import app

    print(f"\nEvaluando el flujo con {len(casos)} casos...\n")

    resultados = []
    for i, case in enumerate(casos, 1):
        obs = ejecutar_caso(app, case)
        checks = evaluar(case, obs)
        ok = all(checks.values())
        resultados.append({"case": case, "obs": obs, "checks": checks, "ok": ok})

        marca = "OK  " if ok else "FALLA"
        fallidos = [k for k, v in checks.items() if not v]
        detalle = f" <- {', '.join(fallidos)}" if fallidos else ""
        print(f"[{i:>2}/{len(casos)}] {marca} {case['id']} | ruta={obs['ruta']:<10} {obs['duracion_s']:>5.2f}s{detalle}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    salida = out_dir / "flow_results.json"
    salida.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")

    # Resumen por agente
    def tasa(nombre_check):
        vals = [r["checks"][nombre_check] for r in resultados if nombre_check in r["checks"]]
        return porcentaje(sum(vals), len(vals)), len(vals)

    print("\n" + "=" * 58)
    print("  EFECTIVIDAD POR AGENTE")
    print("=" * 58)
    for etiqueta, check in [
        ("Orquestador (routing)", "routing"),
        ("Clasificador (categoría)", "clasificacion"),
        ("Clasificador (reporte vago)", "paso_final"),
        ("Clasificador (no registra)", "sin_tools"),
        ("Recomendación (tools)", "tools"),
        ("RAG (contexto esperado)", "rag"),
        ("RAG (sin duplicados)", "rag_diversidad"),
        ("FAQ (rama correcta)", "faq_branch"),
    ]:
        pct, n = tasa(check)
        valor = f"{pct:>5.1f}%" if n else "  n/a"
        print(f"  {etiqueta:<28} {valor}  ({n} casos)")

    global_ok = sum(1 for r in resultados if r["ok"])
    print("-" * 58)
    print(f"  {'CASOS 100% CORRECTOS':<28} {porcentaje(global_ok, len(resultados)):>5.1f}%  ({global_ok}/{len(resultados)})")
    print("=" * 58)
    print(f"\nResultados crudos -> {salida}\n")

    return 0 if global_ok == len(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
