"""Unit tests for NetworkX graph construction and sync operations.

Tests cover:
- Graph construction from DuckDB nodes/edges
- Node and edge attribute mapping
- Tag node immutable status
- Graph caching and rebuild behavior
- Sync operations for nodes and edges
- Performance benchmark (<5s for 10k nodes)
"""

# flake8: noqa: E402
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Add src/python to sys.path for imports
sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import duckdb
import networkx as nx
from graph import build_graph, get_graph, rebuild_graph, sync_edge, sync_node
from persistence.duckdb_connection import get_connection
from persistence.duckdb_init import initialize_database


class TestNetworkXGraphConstruction(unittest.TestCase):
    """Tests for networkx_wrapper module."""

    def setUp(self) -> None:
        """Create temporary database with schema and sample data."""
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        # Initialize schema
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))
        # Reset global singleton between tests
        import graph.singleton as singleton

        singleton._graph = None

    def tearDown(self) -> None:
        """Close connection and clean up temp files."""
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        # Reset global singleton
        import graph.singleton as singleton

        singleton._graph = None

    def _insert_nodes(self, nodes: list[tuple]) -> None:
        """Helper: insert node tuples (id, type, name, definition, tag, status)."""
        for node in nodes:
            self.con.execute(
                """
                INSERT INTO nodes (id, type, name, definition, tag, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                node,
            )

    def _insert_edges(self, edges: list[tuple]) -> None:
        """Helper: insert edge tuples (source_id, target_id, edge_type, metadata_json)."""
        for edge in edges:
            self.con.execute(
                """
                INSERT INTO edges (source_id, target_id, edge_type, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                edge,
            )

    def test_build_graph_empty(self) -> None:
        """Empty nodes/edges tables produce an empty graph."""
        G = build_graph(self.con)
        self.assertIsInstance(G, nx.DiGraph)
        self.assertEqual(G.number_of_nodes(), 0)
        self.assertEqual(G.number_of_edges(), 0)

    def test_build_graph_with_nodes(self) -> None:
        """Nodes from DuckDB are added with correct NetworkX attributes."""
        self._insert_nodes(
            [
                (1, "code", "Code One", "Definition 1", "TagA", "draft"),
                (2, "theme", "Theme One", "Narrative 2", "TagB", "approved"),
                (3, "interpretation", "Interp One", "Interpretation 3", None, "draft"),
                (4, "tag", "TagNode", "Ontology tag", None, "immutable"),
            ]
        )
        G = build_graph(self.con)
        self.assertEqual(G.number_of_nodes(), 4)
        # Check node attributes
        node_data = G.nodes[1]
        self.assertEqual(node_data["type"], "code")
        self.assertEqual(node_data["name"], "Code One")
        self.assertEqual(node_data["definition"], "Definition 1")
        self.assertEqual(node_data["tag"], "TagA")
        self.assertEqual(node_data["status"], "draft")

    def test_build_graph_with_edges(self) -> None:
        """Edges from DuckDB are added with correct type and metadata."""
        self._insert_nodes(
            [
                (1, "code", "C1", None, None, "draft"),
                (2, "code", "C2", None, None, "draft"),
            ]
        )
        self._insert_edges(
            [
                (1, 2, "derived-from", '{"reason": "refinement"}'),
                (2, 1, "neighbor", None),
            ]
        )
        G = build_graph(self.con)
        self.assertEqual(G.number_of_edges(), 2)
        edge_data = G.edges[1, 2]
        self.assertEqual(edge_data["type"], "derived-from")
        self.assertEqual(edge_data["metadata"], {"reason": "refinement"})
        edge_data2 = G.edges[2, 1]
        self.assertEqual(edge_data2["type"], "neighbor")
        self.assertIsNone(edge_data2["metadata"])

    def test_build_graph_tag_nodes_are_immutable(self) -> None:
        """Tag nodes loaded from DuckDB are marked with status='immutable'."""
        # Simulate tag node row (in practice inserted by ontology loader)
        self._insert_nodes(
            [
                (10, "tag", "Problem", "Top-level tag", None, "immutable"),
                (11, "tag", "Problem.Cause", "Causes", None, "immutable"),
            ]
        )
        G = build_graph(self.con)
        for nid in [10, 11]:
            self.assertEqual(G.nodes[nid]["type"], "tag")
            self.assertEqual(G.nodes[nid]["status"], "immutable")

    def test_get_graph_caches_singleton(self) -> None:
        """get_graph() returns the same object on repeated calls."""
        G1 = get_graph(db_path=self.db_path)
        G2 = get_graph(db_path=self.db_path)
        self.assertIs(G1, G2, "get_graph should return cached singleton")

    def test_rebuild_graph_forces_reload(self) -> None:
        """rebuild_graph() clears cache and returns a new graph object."""
        # Build initial graph with 1 node
        self._insert_nodes([(1, "code", "Initial", None, None, "draft")])
        G1 = get_graph(db_path=self.db_path)
        self.assertEqual(G1.number_of_nodes(), 1)
        # Add another node directly to DB (graph unaware)
        self._insert_nodes([(2, "code", "Added Later", None, None, "draft")])
        # get_graph() returns stale cache
        G2 = get_graph(db_path=self.db_path)
        self.assertEqual(G2.number_of_nodes(), 1)
        # rebuild_graph() returns fresh graph
        G3 = rebuild_graph(db_path=self.db_path)
        self.assertEqual(G3.number_of_nodes(), 2)
        self.assertIsNot(G3, G1)
        # Subsequent get_graph() returns rebuilt singleton
        G4 = get_graph(db_path=self.db_path)
        self.assertIs(G4, G3)
        self.assertEqual(G4.number_of_nodes(), 2)

    def test_sync_node_updates_existing(self) -> None:
        """sync_node() updates an existing node's attributes in the graph."""
        self._insert_nodes([(1, "code", "Original", None, "TagX", "draft")])
        G_initial = get_graph(db_path=self.db_path)
        self.assertEqual(G_initial.nodes[1]["name"], "Original")
        # Update directly in DB
        self.con.execute(
            "UPDATE nodes SET name = ? WHERE id = ?",
            ["Updated", 1],
        )
        # Sync the node
        sync_node(1, db_path=self.db_path)
        G_after = get_graph(db_path=self.db_path)
        self.assertEqual(G_after.nodes[1]["name"], "Updated")

    def test_sync_node_adds_missing(self) -> None:
        """sync_node() adds a node that exists in DB but not in graph."""
        # Build graph with one node
        self._insert_nodes([(1, "code", "Existing", None, None, "draft")])
        get_graph(db_path=self.db_path)
        # Insert another node in DB without rebuilding
        self._insert_nodes([(2, "code", "Newly Added", None, None, "draft")])
        # Sync the new node
        sync_node(2, db_path=self.db_path)
        G = get_graph(db_path=self.db_path)
        self.assertIn(2, G.nodes)
        self.assertEqual(G.nodes[2]["name"], "Newly Added")

    def test_sync_node_noop_when_missing(self) -> None:
        """sync_node() logs warning and does nothing if node_id not in DB."""
        self._insert_nodes([(1, "code", "Exists", None, None, "draft")])
        get_graph(db_path=self.db_path)
        # Sync non-existent node should not raise
        try:
            sync_node(999, db_path=self.db_path)
        except Exception as e:
            self.fail(f"sync_node raised unexpectedly: {e}")

    def test_sync_edge_updates_existing(self) -> None:
        """sync_edge() updates an existing edge's metadata."""
        self._insert_nodes(
            [
                (1, "code", "C1", None, None, "draft"),
                (2, "code", "C2", None, None, "draft"),
            ]
        )
        self._insert_edges([(1, 2, "derived-from", '{"v": 1}')])
        get_graph(db_path=self.db_path)
        G = get_graph(db_path=self.db_path)
        self.assertEqual(G.edges[1, 2]["metadata"], {"v": 1})
        # Update edge in DB
        self.con.execute(
            "UPDATE edges SET metadata_json = ? WHERE source_id = ? AND target_id = ? AND edge_type = ?",
            ['{"v": 2}', 1, 2, "derived-from"],
        )
        sync_edge(1, 2, "derived-from", db_path=self.db_path)
        G_after = get_graph(db_path=self.db_path)
        self.assertEqual(G_after.edges[1, 2]["metadata"], {"v": 2})

    def test_sync_edge_adds_missing(self) -> None:
        """sync_edge() adds an edge that exists in DB but not in graph."""
        self._insert_nodes(
            [
                (1, "code", "C1", None, None, "draft"),
                (2, "code", "C2", None, None, "draft"),
            ]
        )
        get_graph(db_path=self.db_path)  # Graph exists with no edge
        self._insert_edges([(1, 2, "neighbor", None)])
        sync_edge(1, 2, "neighbor", db_path=self.db_path)
        G = get_graph(db_path=self.db_path)
        self.assertTrue(G.has_edge(1, 2))
        self.assertEqual(G.edges[1, 2]["type"], "neighbor")

    def test_sync_edge_noop_when_missing(self) -> None:
        """sync_edge() logs warning and no-ops if edge not in DB."""
        self._insert_nodes(
            [
                (1, "code", "C1", None, None, "draft"),
                (2, "code", "C2", None, None, "draft"),
            ]
        )
        get_graph(db_path=self.db_path)
        try:
            sync_edge(1, 2, "nonexistent-type", db_path=self.db_path)
        except Exception as e:
            self.fail(f"sync_edge raised unexpectedly: {e}")

    def test_performance_10k_nodes(self) -> None:
        """Graph construction completes in <5 seconds for 10,000 nodes."""
        # Insert 10k nodes
        batch = [
            (i, "code", f"Code{i}", f"Definition{i}", f"Tag{i % 10}", "draft")
            for i in range(1, 10001)
        ]
        self.con.executemany(
            """
            INSERT INTO nodes (id, type, name, definition, tag, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            batch,
        )
        # Measure build_graph time
        start = time.time()
        G = build_graph(self.con)
        elapsed = time.time() - start
        self.assertEqual(G.number_of_nodes(), 10000)
        self.assertLess(elapsed, 5.0, f"Build took {elapsed:.3f}s, expected <5s")


if __name__ == "__main__":
    unittest.main()
