"""
Golden dataset — regresión del clasificador.

Corre los 30 incidentes de incidents.json contra el classifier_agent y compara
categoría y prioridad contra el ground truth. Es el set de referencia estable:
si un cambio de prompt o de modelo lo mueve, hay una regresión.

A diferencia de las otras dos evaluaciones, esta no necesita el servidor levantado
ni Postgres corriendo — el clasificador no toca la base. Solo requiere OPENAI_API_KEY.

Uso:
    python golden_dataset/run_golden.py
    python golden_dataset/run_golden.py --limit 5
    python golden_dataset/run_golden.py --solo-categoria Seguridad
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)

from langchain_core.messages import HumanMessage

BASE_DIR = Path(__file__).parent
DATASET = BASE_DIR / "incidents.json"
RESULTS = BASE_DIR / "results"


def ejecutar(case: dict) -> dict:
    from agents.classifier_agent import classifier_agent

    state = {"messages": [HumanMessage(content=case["user_input"])]}
    inicio = time.perf_counter()
    try:
        salida = classifier_agent(state)
        error = None
    except Exception as e:
        salida, error = {}, str(e)
    duracion = time.perf_counter() - inicio

    return {
        "category": salida.get("category"),
        "priority": salida.get("priority"),
        "possible_causes": salida.get("possible_causes") or [],
        "current_step": salida.get("current_step"),
        "duracion_s": round(duracion, 2),
        "error": error,
    }


def main():
    parser = argparse.ArgumentParser(description="Golden dataset del clasificador de incidentes.")
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument("--out-dir", default=str(RESULTS))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--solo-categoria", default=None, help="Filtra por categoría esperada.")
    args = parser.parse_args()

    data = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    casos = data["cases"]
    if args.solo_categoria:
        casos = [c for c in casos if c["expected_category"] == args.solo_categoria]
    if args.limit:
        casos = casos[: args.limit]

    print(f"\nGolden dataset — {len(casos)} incidentes\n")

    resultados = []
    for i, case in enumerate(casos, 1):
        obs = ejecutar(case)
        cat_ok = obs["category"] == case["expected_category"]
        pri_ok = obs["priority"] == case["expected_priority"]
        resultados.append({"case": case, "obs": obs, "cat_ok": cat_ok, "pri_ok": pri_ok})

        marca = "OK  " if (cat_ok and pri_ok) else "FALLA"
        detalle = ""
        if not cat_ok:
            detalle += f" | categoria: esperaba {case['expected_category']}, dio {obs['category']}"
        if not pri_ok:
            detalle += f" | prioridad: esperaba {case['expected_priority']}, dio {obs['priority']}"
        print(f"[{i:>2}/{len(casos)}] {marca} {case['id']} {obs['duracion_s']:>5.2f}s{detalle}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "golden_results.json").write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ── Resumen ──
    n = len(resultados)
    cat = sum(r["cat_ok"] for r in resultados)
    pri = sum(r["pri_ok"] for r in resultados)
    ambos = sum(r["cat_ok"] and r["pri_ok"] for r in resultados)

    def pct(x):
        return f"{100 * x / n:.1f}%" if n else "n/a"

    print("\n" + "=" * 58)
    print("  GOLDEN DATASET — CLASIFICADOR")
    print("=" * 58)
    print(f"  {'Categoría correcta':<28} {pct(cat):>6}  ({cat}/{n})")
    print(f"  {'Prioridad correcta':<28} {pct(pri):>6}  ({pri}/{n})")
    print(f"  {'Ambas correctas':<28} {pct(ambos):>6}  ({ambos}/{n})")

    por_cat = defaultdict(lambda: [0, 0])
    for r in resultados:
        c = r["case"]["expected_category"]
        por_cat[c][1] += 1
        por_cat[c][0] += r["cat_ok"]

    print("-" * 58)
    print("  Acierto de categoría, por categoría esperada:")
    for c in sorted(por_cat):
        ok, tot = por_cat[c]
        print(f"    {c:<24} {100 * ok / tot:>5.1f}%  ({ok}/{tot})")

    fallos = [r for r in resultados if not (r["cat_ok"] and r["pri_ok"])]
    if fallos:
        print("-" * 58)
        print("  Casos a revisar:")
        for r in fallos:
            c, o = r["case"], r["obs"]
            print(f"    {c['id']}: {c['user_input'][:58]}...")
            print(f"       esperado {c['expected_category']} / {c['expected_priority']}"
                  f"  ->  obtenido {o['category']} / {o['priority']}")
            print(f"       {c['nota']}")

    print("=" * 58)
    print(f"\nResultados crudos -> {out_dir / 'golden_results.json'}\n")

    return 0 if not fallos else 1


if __name__ == "__main__":
    sys.exit(main())
