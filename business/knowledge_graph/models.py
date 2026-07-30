"""Pydantic models for the Financial Knowledge Graph.

Defines :class:`GraphNode`, :class:`GraphEdge`, and
:class:`KnowledgeGraph` — a directed graph of financial entities
and their relationships used for lineage, impact analysis, and
semantic navigation.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    """A node in the financial knowledge graph.

    Represents a core financial concept or entity.

    Attributes:
        node_id: Unique identifier for this node.
        label: Human-readable display label.
        node_type: Semantic type (e.g. ``"account"``, ``"statement"``).
        properties: Arbitrary key-value metadata.
    """

    node_id: str = Field(description="Unique identifier for this node")
    label: str = Field(description="Human-readable display label")
    node_type: str = Field(
        description="Semantic type e.g. account, statement, process",
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata",
    )


class GraphEdge(BaseModel):
    """A directed edge between two :class:`GraphNode` instances.

    Attributes:
        source_id: ``node_id`` of the source node.
        target_id: ``node_id`` of the target node.
        relationship: Label describing the edge (e.g. ``"feeds_into"``).
        properties: Arbitrary key-value metadata.
    """

    source_id: str = Field(description="node_id of the source node")
    target_id: str = Field(description="node_id of the target node")
    relationship: str = Field(
        description="Label describing the edge e.g. feeds_into",
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata",
    )


class KnowledgeGraph(BaseModel):
    """A directed knowledge graph of financial entities.

    Supports node/edge CRUD, path finding, neighbour queries,
    and subgraph extraction.

    Attributes:
        nodes: Mapping of ``node_id`` to :class:`GraphNode`.
        edges: List of all edges in the graph.
    """

    nodes: dict[str, GraphNode] = Field(
        default_factory=dict,
        description="Mapping of node_id to GraphNode",
    )
    edges: list[GraphEdge] = Field(
        default_factory=list,
        description="List of all edges in the graph",
    )

    # ── internal adjacency cache ─────────────────────────────────
    _adjacency: dict[str, list[tuple[str, str, str]]] = {}
    """node_id -> list of (target_id, relationship, edge_source_id)"""

    def model_post_init(self, __context: Any) -> None:
        """Build adjacency cache after initialisation."""
        self._rebuild_adjacency()

    def _rebuild_adjacency(self) -> None:
        """Rebuild the adjacency list from the current edges."""
        self._adjacency: dict[str, list[tuple[str, str, str]]] = {}
        # Outgoing edges
        for edge in self.edges:
            self._adjacency.setdefault(edge.source_id, []).append(
                (edge.target_id, edge.relationship, edge.source_id),
            )
        # Also track incoming by adding source as neighbour of target
        # (we'll store both directions for easy traversal)
        for edge in self.edges:
            self._adjacency.setdefault(edge.target_id, [])

    def add_node(self, node: GraphNode) -> GraphNode:
        """Add a node to the graph. Replaces an existing node with the same ID.

        Args:
            node: The node to add.

        Returns:
            The added node.
        """
        self.nodes[node.node_id] = node
        return node

    def add_edge(self, edge: GraphEdge) -> GraphEdge:
        """Add an edge to the graph and update the adjacency cache.

        Args:
            edge: The edge to add.

        Returns:
            The added edge.
        """
        self.edges.append(edge)
        self._adjacency.setdefault(edge.source_id, []).append(
            (edge.target_id, edge.relationship, edge.source_id),
        )
        self._adjacency.setdefault(edge.target_id, [])
        return edge

    def neighbors(self, node_id: str) -> list[GraphNode]:
        """Return all direct neighbours (outgoing edges) of a node.

        Args:
            node_id: The node to find neighbours for.

        Returns:
            List of neighbour nodes reachable via outgoing edges.
        """
        adj = self._adjacency.get(node_id, [])
        targets = [t[0] for t in adj]
        return [self.nodes[t] for t in targets if t in self.nodes]

    def incoming(self, node_id: str) -> list[GraphNode]:
        """Return all nodes that have edges pointing to *node_id*.

        Args:
            node_id: The target node.

        Returns:
            List of source nodes.
        """
        sources: list[GraphNode] = []
        for edge in self.edges:
            if edge.target_id == node_id and edge.source_id in self.nodes:
                sources.append(self.nodes[edge.source_id])
        return sources

    def find_path(self, from_id: str, to_id: str) -> list[list[str]]:
        """Find all simple paths between two nodes (DFS backtracking).

        Args:
            from_id: Starting node ID.
            to_id: Target node ID.

        Returns:
            List of paths, where each path is a list of node IDs.
            Returns an empty list if no path exists.
        """
        if from_id not in self.nodes or to_id not in self.nodes:
            return []

        paths: list[list[str]] = []

        def _dfs(current: str, target: str, visited: set[str], path: list[str]) -> None:
            if current == target:
                paths.append(list(path))
                return
            adj = self._adjacency.get(current, [])
            for next_id, _rel, _src in adj:
                if next_id not in visited and next_id in self.nodes:
                    visited.add(next_id)
                    path.append(next_id)
                    _dfs(next_id, target, visited, path)
                    path.pop()
                    visited.discard(next_id)

        _dfs(from_id, to_id, {from_id}, [from_id])
        return paths

    def shortest_path(self, from_id: str, to_id: str) -> list[str]:
        """Find the shortest path (fewest edges) between two nodes (BFS).

        Args:
            from_id: Starting node ID.
            to_id: Target node ID.

        Returns:
            List of node IDs from start to target, or empty if no path.
        """
        if from_id not in self.nodes or to_id not in self.nodes:
            return []

        visited: set[str] = {from_id}
        queue: list[list[str]] = [[from_id]]

        while queue:
            path = queue.pop(0)
            last = path[-1]
            if last == to_id:
                return path
            adj = self._adjacency.get(last, [])
            for next_id, _rel, _src in adj:
                if next_id not in visited and next_id in self.nodes:
                    visited.add(next_id)
                    new_path = list(path)
                    new_path.append(next_id)
                    queue.append(new_path)

        return []

    def subgraph(self, node_types: set[str]) -> KnowledgeGraph:
        """Extract a subgraph containing only nodes of the given types.

        Args:
            node_types: Set of node_type values to include.

        Returns:
            A new :class:`KnowledgeGraph` with filtered nodes and
            edges that connect them.
        """
        filtered_nodes = {
            nid: node for nid, node in self.nodes.items() if node.node_type in node_types
        }
        filtered_node_ids = set(filtered_nodes.keys())
        filtered_edges = [
            edge
            for edge in self.edges
            if edge.source_id in filtered_node_ids and edge.target_id in filtered_node_ids
        ]
        return KnowledgeGraph(
            nodes=filtered_nodes,
            edges=filtered_edges,
        )

    def find_nodes_by_type(self, node_type: str) -> list[GraphNode]:
        """Find all nodes with the given *node_type*.

        Args:
            node_type: The semantic type to filter by.

        Returns:
            List of matching nodes.
        """
        return [n for n in self.nodes.values() if n.node_type == node_type]

    def find_edges_by_relationship(self, relationship: str) -> list[GraphEdge]:
        """Find all edges with the given *relationship* label.

        Args:
            relationship: The relationship label to filter by.

        Returns:
            List of matching edges.
        """
        return [e for e in self.edges if e.relationship == relationship]

    def traverse(
        self,
        start_id: str,
        max_depth: int = 10,
    ) -> Generator[tuple[str, str, int], None, None]:
        """BFS traversal yielding (node_id, relationship, depth) tuples.

        Args:
            start_id: Starting node ID.
            max_depth: Maximum traversal depth.

        Yields:
            ``(node_id, relationship_from_parent, depth)`` tuples.
        """
        if start_id not in self.nodes:
            return
        visited: set[str] = {start_id}
        queue: list[tuple[str, str | None, int]] = [(start_id, None, 0)]
        while queue:
            current, rel, depth = queue.pop(0)
            yield (current, rel or "", depth)
            if depth >= max_depth:
                continue
            adj = self._adjacency.get(current, [])
            for next_id, edge_rel, _src in adj:
                if next_id not in visited:
                    visited.add(next_id)
                    queue.append((next_id, edge_rel, depth + 1))

    def __len__(self) -> int:
        """Return the number of nodes in the graph."""
        return len(self.nodes)

    def __contains__(self, item: object) -> bool:
        """Check if a node_id string or GraphNode exists in the graph."""
        if isinstance(item, str):
            return item in self.nodes
        if isinstance(item, GraphNode):
            return item.node_id in self.nodes
        return False
