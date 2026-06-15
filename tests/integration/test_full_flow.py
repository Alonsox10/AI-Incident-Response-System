"""
Test de integración del flujo completo del sistema de respuesta a incidentes.

En lugar de importar `graphs/incidente_graph.py` (que conecta a PostgreSQL en
el momento del import), reconstruimos el mismo grafo aquí usando MemorySaver
en memoria.  Todos los LLMs y la conexión a base de datos se mockean.

Flujo completo que se valida:
  orchestrator → classifier → orchestrator → recommendation → tools → END
"""
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage, AIMessage

from schemas.models import OrquestatorOutput, IncidentClassificationOutput
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from state.state import IncidentState
from agents.orchestrator_agent import orchestrator_agent
from agents.classifier_agent import classifier_agent
from agents.recomendation_agent import recomendation_agent
from tools.incidente_tools import search_incident_by_category, insert_incident
from graphs.router import router


def build_test_graph():
    """
    Reconstruye el grafo de incidentes sin dependencia de PostgreSQL.
    Usa MemorySaver (en memoria) como checkpointer.
    """
    graph = StateGraph(IncidentState)
    graph.add_node("orchestrator", orchestrator_agent)
    graph.set_entry_point("orchestrator")
    graph.add_node("classifier", classifier_agent)
    graph.add_node("recommendation", recomendation_agent)
    graph.add_node("tools", ToolNode([search_incident_by_category, insert_incident]))

    graph.add_edge("classifier", "orchestrator")
    graph.add_edge("recommendation", "tools")
    graph.add_edge("tools", END)

    routes = {
        "classifier": "classifier",
        "recommendation": "recommendation",
        "end": END,
    }
    graph.add_conditional_edges("orchestrator", router, routes)

    return graph.compile(checkpointer=MemorySaver())


class TestFullIncidentFlow:

    def test_complete_workflow_state_after_execution(self):
        """
        El estado final debe tener categoría, prioridad, causas y current_step
        correctamente poblados después de correr el flujo completo.
        """
        # El orchestrator es llamado 2 veces: primero envía al classifier,
        # luego a recommendation.
        orchestrator_responses = [
            OrquestatorOutput(next_agent="classifier"),
            OrquestatorOutput(next_agent="recommendation"),
        ]

        # El recommendation agent devuelve un AIMessage con una tool_call
        # para que ToolNode la ejecute.
        llm_recommendation_response = AIMessage(
            content="",
            tool_calls=[{
                "id": "call_test_001",
                "name": "search_incident_by_category",
                "args": {"category": "Error backend"},
                "type": "tool_call",
            }],
        )

        # Mock de la conexión a PostgreSQL usada por las tools
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("Backend server down", "High"),
            ("API response timeout", "Medium"),
        ]

        with patch("agents.orchestrator_agent.llm_structured") as mock_orch, \
             patch("agents.classifier_agent.llm_structured") as mock_cls, \
             patch("agents.recomendation_agent.llm_bind_tools") as mock_rec, \
             patch("tools.incidente_tools.get_connection", return_value=mock_conn):

            mock_orch.invoke.side_effect = orchestrator_responses
            mock_cls.invoke.return_value = IncidentClassificationOutput(
                category="Error backend",
                priority="High",
                possible_causes=["Timeout de conexión", "Memoria agotada"],
            )
            mock_rec.invoke.return_value = llm_recommendation_response

            app = build_test_graph()
            config = {"configurable": {"thread_id": "integration-test-001"}}
            final_state = app.invoke(
                {"messages": [HumanMessage(content="El servidor de backend no responde")]},
                config=config,
            )

        assert final_state["category"] == "Error backend"
        assert final_state["priority"] == "High"
        assert "Timeout de conexión" in final_state["possible_causes"]
        assert final_state["current_step"] == "recommendation_done"

    def test_each_agent_is_called_correct_number_of_times(self):
        """
        Verifica que el grafo ejecuta exactamente:
        - orchestrator x2  (routing inicial + routing tras classifier)
        - classifier x1
        - recommendation x1
        """
        orchestrator_responses = [
            OrquestatorOutput(next_agent="classifier"),
            OrquestatorOutput(next_agent="recommendation"),
        ]
        llm_recommendation_response = AIMessage(
            content="",
            tool_calls=[{
                "id": "call_test_002",
                "name": "search_incident_by_category",
                "args": {"category": "Seguridad"},
                "type": "tool_call",
            }],
        )
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("agents.orchestrator_agent.llm_structured") as mock_orch, \
             patch("agents.classifier_agent.llm_structured") as mock_cls, \
             patch("agents.recomendation_agent.llm_bind_tools") as mock_rec, \
             patch("tools.incidente_tools.get_connection", return_value=mock_conn):

            mock_orch.invoke.side_effect = orchestrator_responses
            mock_cls.invoke.return_value = IncidentClassificationOutput(
                category="Seguridad",
                priority="High",
                possible_causes=["Acceso no autorizado"],
            )
            mock_rec.invoke.return_value = llm_recommendation_response

            app = build_test_graph()
            config = {"configurable": {"thread_id": "integration-test-002"}}
            app.invoke(
                {"messages": [HumanMessage(content="Detectamos una brecha de seguridad")]},
                config=config,
            )

        assert mock_orch.invoke.call_count == 2
        assert mock_cls.invoke.call_count == 1
        assert mock_rec.invoke.call_count == 1

    def test_orchestrator_shortcuts_to_end(self):
        """
        Si el orchestrator decide 'end' en la primera llamada, el workflow
        termina sin llamar al classifier ni al recommendation agent.
        """
        with patch("agents.orchestrator_agent.llm_structured") as mock_orch, \
             patch("agents.classifier_agent.llm_structured") as mock_cls, \
             patch("agents.recomendation_agent.llm_bind_tools") as mock_rec:

            mock_orch.invoke.return_value = OrquestatorOutput(next_agent="end")

            app = build_test_graph()
            config = {"configurable": {"thread_id": "integration-test-003"}}
            app.invoke(
                {"messages": [HumanMessage(content="Todo está bien")]},
                config=config,
            )

        mock_cls.invoke.assert_not_called()
        mock_rec.invoke.assert_not_called()

    def test_database_tool_is_called_with_correct_category(self):
        """
        La tool search_incident_by_category debe recibir la categoría
        exacta que el recommendation agent especificó en el tool_call.
        """
        orchestrator_responses = [
            OrquestatorOutput(next_agent="classifier"),
            OrquestatorOutput(next_agent="recommendation"),
        ]
        llm_recommendation_response = AIMessage(
            content="",
            tool_calls=[{
                "id": "call_test_003",
                "name": "search_incident_by_category",
                "args": {"category": "Redes"},
                "type": "tool_call",
            }],
        )
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("agents.orchestrator_agent.llm_structured") as mock_orch, \
             patch("agents.classifier_agent.llm_structured") as mock_cls, \
             patch("agents.recomendation_agent.llm_bind_tools") as mock_rec, \
             patch("tools.incidente_tools.get_connection", return_value=mock_conn):

            mock_orch.invoke.side_effect = orchestrator_responses
            mock_cls.invoke.return_value = IncidentClassificationOutput(
                category="Redes",
                priority="Medium",
                possible_causes=["Latencia alta"],
            )
            mock_rec.invoke.return_value = llm_recommendation_response

            app = build_test_graph()
            config = {"configurable": {"thread_id": "integration-test-004"}}
            app.invoke(
                {"messages": [HumanMessage(content="La red está muy lenta")]},
                config=config,
            )

        # Verifica que el execute de la DB fue llamado con "Redes"
        # call_args[0] = (query_sql, params_tuple) → params_tuple es call_args[0][1]
        sql_params = mock_conn.execute.call_args[0][1]
        assert "Redes" in sql_params
