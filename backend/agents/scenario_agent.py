from backend.models.state import PipelineState, RootCauseFinding, Scenario


def generate_scenarios(root_causes: list[RootCauseFinding]) -> list[Scenario]:
    scenarios = [
        Scenario(
            name="Base Case",
            description="Current trajectory with identified root causes addressed",
            assumptions={"growth_rate": 0.05, "cost_inflation": 0.03},
            revenue_impact=0.0,
            ebitda_impact=0.0,
            cash_impact=0.0,
            probability_assessment="high",
        ),
    ]
    return scenarios


def scenario_node(state: PipelineState) -> dict:
    root_causes = state.get("root_causes", [])
    scenarios = generate_scenarios(root_causes)
    return {"scenarios": scenarios, "current_step": "scenario_complete"}
