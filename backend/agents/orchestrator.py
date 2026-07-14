from langgraph.graph import StateGraph, END
from langgraph.checkpoint.base import BaseCheckpointSaver
from backend.models.state import PipelineState


def _route_after_variance(state: PipelineState) -> str:
    material_variances = [v for v in state.get("variances", []) if v.is_material]
    if not material_variances:
        return "commentary"
    return "root_cause"


def build_graph(checkpointer: BaseCheckpointSaver | None = None) -> StateGraph:
    from backend.agents.ingestion_agent import ingestion_node
    from backend.agents.variance_agent import variance_node
    from backend.agents.root_cause_agent import root_cause_node
    from backend.agents.commentary_agent import commentary_node
    from backend.agents.scenario_agent import scenario_node

    builder = StateGraph(PipelineState)

    builder.add_node("ingestion", ingestion_node)
    builder.add_node("variance_detection", variance_node)
    builder.add_node("root_cause", root_cause_node)
    builder.add_node("commentary", commentary_node)
    builder.add_node("scenario", scenario_node)

    builder.set_entry_point("ingestion")
    builder.add_edge("ingestion", "variance_detection")
    builder.add_conditional_edges(
        "variance_detection",
        _route_after_variance,
        {"root_cause": "root_cause", "commentary": "commentary"},
    )
    builder.add_edge("root_cause", "commentary")
    builder.add_edge("commentary", "scenario")
    builder.add_edge("scenario", END)

    compile_kwargs = {}
    if checkpointer:
        compile_kwargs["checkpointer"] = checkpointer

    return builder.compile(**compile_kwargs)
