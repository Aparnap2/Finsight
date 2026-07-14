import pytest
from backend.agents.orchestrator import build_graph
from backend.models.state import PipelineState


def test_graph_compiles():
    graph = build_graph(checkpointer=None)
    assert graph is not None


def test_graph_has_expected_nodes():
    graph = build_graph(checkpointer=None)
    nodes = list(graph.get_graph().nodes)
    assert "ingestion" in nodes
    assert "variance_detection" in nodes
    assert "root_cause" in nodes
    assert "commentary" in nodes
    assert "scenario" in nodes
