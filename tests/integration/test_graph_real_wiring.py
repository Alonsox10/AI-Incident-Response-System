"""
Integración sobre el grafo REAL de `graphs/incidente_graph.py`.

Por qué hace falta además de `test_full_flow.py`: ese test **reconstruye** un grafo
propio y lo cablea distinto del de producción — usa `recommendation → tools → END`,
sin `recommendation_router` ni la vuelta `tools → recommendation`. Es decir, valida
los agentes, pero no el cableado que corre de verdad: la segunda pasada del agente
de recomendación (la que sintetiza la respuesta con el contexto RAG ya recuperado)
nunca se ejercita, y una regresión en esos edges pasaría la suite en verde.

Acá se importa el objeto `graph` de producción y solo se le cambia el checkpointer
(MemorySaver en vez de AsyncPostgresSaver) para no necesitar Postgres. Los edges,
el `ToolNode`, el router y los envoltorios `medir_nodo` son los reales.

Lo que se dobla y por qué: el LLM (gasto y no determinismo), los embeddings y las
búsquedas vectoriales (red + Postgres), y el pool (Postgres). Queda real todo lo que
se está probando: el cableado del grafo, el routing, las tools y los agentes.
"""
import pytest
from unittest.mock import AsyncMock, patch
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from graphs.incidente_graph import graph
from schemas.models import IncidentClassificationOutput, OrquestatorOutput


@pytest.fixture
def app():
    """El grafo de producción, compilado con un checkpointer en memoria."""
    return graph.compile(checkpointer=MemorySaver())


@pytest.fixture
def config():
    return {"configurable": {"thread_id": "test-wiring"}}


class PoolFalso:
    """Doble del pool asíncrono: `pool.connection()` es un context manager async."""

    def __init__(self, filas=None):
        self.filas = filas or []
        self.ejecutadas = []

    def connection(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def execute(self, query, params=None):
        self.ejecutadas.append((query, params))
        cur = AsyncMock()
        cur.fetchall.return_value = self.filas
        cur.fetchone.return_value = self.filas[0] if self.filas else None
        return cur


def _estado(texto="El servidor de backend devuelve 500 en todas las peticiones"):
    return {
        "messages": [HumanMessage(content=texto)],
        "category": None,
        "priority": None,
        "possible_causes": [],
        "recommendations": [],
        "next_agent": None,
        "current_step": None,
    }


PRIMERA_PASADA = AIMessage(
    content="",
    tool_calls=[
        {"id": "c1", "name": "search_knowledge_base_rag",
         "args": {"query": "backend 500"}, "type": "tool_call"},
        {"id": "c2", "name": "search_similar_incidents_rag",
         "args": {"incident_description": "backend 500"}, "type": "tool_call"},
        {"id": "c3", "name": "insert_incident",
         "args": {"title": "Backend 500", "category": "Error backend", "priority": "Alta"},
         "type": "tool_call"},
    ],
)

SEGUNDA_PASADA = AIMessage(
    content="1. Revisa los logs del servicio. 2. Reinicia el pod. 3. Verifica la conexión a la base."
)


def _parches(orquestador, clasificador=None, recomendacion=None, pool=None):
    """Dobla los bordes externos: LLMs, embeddings, búsquedas vectoriales y pool."""
    pool = pool if pool is not None else PoolFalso()
    ctx = [
        patch("agents.orchestrator_agent._coincide_con_faq_documentada",
              new_callable=AsyncMock, return_value=None),
        patch("agents.orchestrator_agent.llm_structured"),
        patch("agents.classifier_agent.llm_structured"),
        patch("agents.recomendation_agent.llm_bind_tools"),
        patch("tools.rag_tools.get_embedding", new_callable=AsyncMock,
              return_value=[0.0] * 1536),
        patch("tools.rag_tools.search_knowledge_base", new_callable=AsyncMock,
              return_value=[{"content": "Runbook: reiniciar el servicio",
                             "source": "runbook.pdf", "similarity": 0.91}]),
        patch("tools.rag_tools.search_similar_incidents", new_callable=AsyncMock,
              return_value=[{"description": "500 masivo", "category": "Error backend",
                             "priority": "Alta", "resolution": "Rollback del despliegue",
                             "similarity": 0.88}]),
        patch("tools.incidente_tools.get_pool", new_callable=AsyncMock,
              return_value=pool),
    ]
    return ctx, pool


class TestDobleParadaDeRecomendacion:
    """El cableado que `test_full_flow.py` no puede ver."""

    async def test_el_flujo_completo_hace_las_dos_pasadas_y_cierra(self, app, config):
        ctx, pool = _parches(None)
        with ctx[0], ctx[1] as orq, ctx[2] as clf, ctx[3] as rec, \
             ctx[4], ctx[5], ctx[6], ctx[7]:
            orq.ainvoke = AsyncMock(side_effect=[
                OrquestatorOutput(next_agent="classifier"),
                OrquestatorOutput(next_agent="recommendation"),
            ])
            clf.ainvoke = AsyncMock(return_value=IncidentClassificationOutput(
                category="Error backend", priority="Alta",
                possible_causes=["Despliegue roto", "Base inalcanzable"],
                informacion_suficiente=True,
            ))
            rec.ainvoke = AsyncMock(side_effect=[PRIMERA_PASADA, SEGUNDA_PASADA])

            final = await app.ainvoke(_estado(), config)

            # La prueba del cableado: el agente de recomendación se invocó DOS veces.
            # Con `tools → END` (como lo cablea el test reconstruido) sería una sola.
            assert rec.ainvoke.await_count == 2, (
                "La segunda pasada no ocurrió: el edge tools → recommendation no se recorrió"
            )

        # La síntesis final, no el mensaje vacío de la primera pasada, es la respuesta.
        assert final["recommendations"] == SEGUNDA_PASADA.content
        assert final["current_step"] == "recommendation_done"
        assert final["category"] == "Error backend"
        assert final["priority"] == "Alta"

    async def test_las_tres_tools_se_ejecutan_y_sus_resultados_llegan_al_historial(self, app, config):
        ctx, pool = _parches(None)
        with ctx[0], ctx[1] as orq, ctx[2] as clf, ctx[3] as rec, \
             ctx[4], ctx[5], ctx[6], ctx[7]:
            orq.ainvoke = AsyncMock(side_effect=[
                OrquestatorOutput(next_agent="classifier"),
                OrquestatorOutput(next_agent="recommendation"),
            ])
            clf.ainvoke = AsyncMock(return_value=IncidentClassificationOutput(
                category="Error backend", priority="Alta",
                possible_causes=["x"], informacion_suficiente=True,
            ))
            rec.ainvoke = AsyncMock(side_effect=[PRIMERA_PASADA, SEGUNDA_PASADA])

            final = await app.ainvoke(_estado(), config)

            # El ToolNode real resolvió las tres tool_calls pedidas en paralelo.
            ejecutadas = {m.name for m in final["messages"] if isinstance(m, ToolMessage)}
            assert ejecutadas == {
                "search_knowledge_base_rag",
                "search_similar_incidents_rag",
                "insert_incident",
            }

            # Y la segunda pasada recibió esos ToolMessages como contexto: sin esto el
            # agente sintetizaría sin RAG, que es justo el fallo silencioso a evitar.
            contexto_segunda_pasada = rec.ainvoke.await_args_list[1].args[0]
            assert any(isinstance(m, ToolMessage) for m in contexto_segunda_pasada)

        # El incidente quedó registrado una sola vez.
        inserts = [q for q, _ in pool.ejecutadas if "INSERT INTO incidents" in q]
        assert len(inserts) == 1


class TestCaminosQueNoRegistranIncidente:
    """Las otras dos formas de terminar. Distinguirlas importa: solo una registra."""

    async def test_el_camino_de_faq_resuelve_en_una_pasada_sin_clasificar(self, app, config):
        pool = PoolFalso()
        with patch("agents.orchestrator_agent._coincide_con_faq_documentada",
                   new_callable=AsyncMock, return_value=0.93), \
             patch("agents.orchestrator_agent.llm_structured") as orq, \
             patch("agents.classifier_agent.llm_structured") as clf, \
             patch("agents.faq_agent.get_embedding", new_callable=AsyncMock,
                   return_value=[0.0] * 1536), \
             patch("agents.faq_agent.search_faqs", new_callable=AsyncMock, return_value=[{
                 "id": 1, "question": "¿Cómo pido una VPN?",
                 "answer": "Abre un ticket en el portal de TI.",
                 "category": "Accesos", "metadata": {}, "similarity": 0.93,
             }]), \
             patch("agents.faq_agent.llm") as faq_llm, \
             patch("tools.incidente_tools.get_pool", new_callable=AsyncMock, return_value=pool):

            orq.ainvoke = AsyncMock()
            final = await app.ainvoke(_estado("¿Cómo pido una VPN?"), config)

            # Pre-chequeo determinístico: ni el LLM del orquestador ni el clasificador
            # ni el LLM de FAQ (alta confianza) se consultaron.
            orq.ainvoke.assert_not_awaited()
            clf.ainvoke.assert_not_called()
            faq_llm.ainvoke.assert_not_called()

        assert final["current_step"] == "faq_done"
        assert final["recommendations"] == "Abre un ticket en el portal de TI."
        # El camino de FAQ no clasifica ni registra nada.
        assert final.get("category") is None
        assert pool.ejecutadas == []

    async def test_un_reporte_vago_termina_en_needs_detail_sin_rag_ni_registro(self, app, config):
        ctx, pool = _parches(None)
        with ctx[0], ctx[1] as orq, ctx[2] as clf, ctx[3] as rec, \
             ctx[4], ctx[5] as kb, ctx[6], ctx[7]:
            orq.ainvoke = AsyncMock(side_effect=[
                OrquestatorOutput(next_agent="classifier"),
                OrquestatorOutput(next_agent="end"),
            ])
            clf.ainvoke = AsyncMock(return_value=IncidentClassificationOutput(
                category="Error backend", priority="Media",
                possible_causes=["qué sé yo"], informacion_suficiente=False,
            ))
            rec.ainvoke = AsyncMock()

            final = await app.ainvoke(_estado("algo no funciona"), config)

            # Ni recomendación, ni RAG, ni registro: el reporte vacío no cuesta tokens
            # de contexto ni ensucia el histórico con un incidente inventado.
            rec.ainvoke.assert_not_awaited()
            kb.assert_not_awaited()

        assert final["current_step"] == "needs_detail"
        # La clasificación se descarta: etiquetar un mensaje sin síntoma es inventar.
        assert final.get("category") is None
        assert final.get("priority") is None
        assert pool.ejecutadas == []


class TestInstrumentacionDelGrafoReal:

    async def test_todos_los_nodos_registrados_pasaron_la_guarda_de_async(self):
        """El grafo real se importa sin TypeError, lo que prueba que los cuatro nodos
        son `async def`. Si alguien vuelve uno síncrono, el import falla acá."""
        nodos = set(graph.nodes) - {"__start__"}
        assert {"orchestrator", "classifier", "recommendation", "faq", "tools"} <= nodos
