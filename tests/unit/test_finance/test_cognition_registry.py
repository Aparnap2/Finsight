from __future__ import annotations


class TestNodeRegistry:
    def test_registry_register_and_get(self):
        from finance.cognition.registry import NodeRegistry
        from finance.cognition.nodes import PlannerNode

        registry = NodeRegistry()
        node = registry.get("planner")
        assert node is not None
        assert node.__class__.__name__ == "PlannerNode"

    def test_registry_returns_none_for_unknown(self):
        from finance.cognition.registry import NodeRegistry

        registry = NodeRegistry()
        assert registry.get("nonexistent") is None

    def test_registry_default_pipeline(self):
        from finance.cognition.registry import NodeRegistry

        registry = NodeRegistry()
        pipeline = registry.default_pipeline()
        assert "planner" in pipeline
        assert "retriever" in pipeline
        assert "executor" in pipeline
        assert "verifier" in pipeline
        assert "reflection" in pipeline

    def test_registry_configure_pipeline(self):
        from finance.cognition.registry import NodeRegistry

        registry = NodeRegistry()
        registry.configure_pipeline(["planner", "verifier"])
        assert registry.get_pipeline() == ["planner", "verifier"]

    def test_registry_configure_unknown_raises(self):
        from finance.cognition.registry import NodeRegistry

        registry = NodeRegistry()
        try:
            registry.configure_pipeline(["nonexistent"])
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_registry_list_nodes(self):
        from finance.cognition.registry import NodeRegistry

        registry = NodeRegistry()
        names = registry.list_nodes()
        assert "planner" in names
        assert "retriever" in names
        assert "executor" in names
        assert "verifier" in names
        assert "reflection" in names

    def test_registry_custom_register(self):
        from finance.cognition.registry import NodeRegistry
        from finance.cognition.nodes import VerifierNode

        registry = NodeRegistry()
        registry.register("custom_verifier", VerifierNode())
        assert registry.get("custom_verifier") is not None

    def test_registry_executor_injected(self):
        from finance.cognition.registry import NodeRegistry

        registry = NodeRegistry()
        node = registry.get("executor")
        assert node is not None

    def test_registry_old_tool_router_not_found(self):
        from finance.cognition.registry import NodeRegistry

        registry = NodeRegistry()
        assert registry.get("tool_router") is None

    def test_registry_with_injected_dependencies(self):
        from finance.cognition.registry import NodeRegistry
        from finance.integration.mock_provider import MockProvider

        provider = MockProvider()
        registry = NodeRegistry(spreadsheet_provider=provider)
        retriever = registry.get("retriever")
        assert retriever is not None
        assert retriever._provider is provider
