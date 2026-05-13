"""Integration test: graph sync after node/edge insertion via persistence API.

Validates acceptance criterion: "insert node via API → graph reflects new node"
Tests the full flow across persistence and graph layers.
"""

# flake8: noqa: E402
import sys
import tempfile
import unittest
from pathlib import Path

# Add src/python to sys.path for imports
sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import duckdb
from graph import get_graph, rebuild_graph, sync_edge, sync_node
from persistence.duckdb_init import initialize_database


class TestGraphSyncIntegration(unittest.TestCase):
    """End-to-end tests for graph synchronization after mutations."""

    def setUp(self) -> None:
        """Initialize isolated database and reset graph singleton."""
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        # Reset graph singleton
        import graph.singleton as singleton

        singleton._graph = None

    def tearDown(self) -> None:
        """Clean up temp files."""
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.singleton as singleton

        singleton._graph = None

    def test_insert_node_via_api_reflects_in_graph(self) -> None:
        """Inserting a node through DuckDB API and calling sync_node() adds it to graph."""
        # Build initial graph (empty)
        G_initial = get_graph(db_path=self.db_path)
        initial_count = G_initial.number_of_nodes()
        self.assertEqual(initial_count, 0)
        # Insert node via DuckDB (simulating persistence API)
        con = duckdb.connect(str(self.db_path))
        result = con.execute(
            """
            INSERT INTO nodes (type, name, definition, tag, status)
            VALUES (?, ?, ?, ?, ?)
            RETURNING id
            """,
            [
                "code",
                "integration_test_code",
                "A code inserted via API",
                "TestTag",
                "draft",
            ],
        ).fetchone()
        new_node_id = result[0]
        con.close()
        # Sync node into graph
        sync_node(new_node_id, db_path=self.db_path)
        # Verify graph reflects new node
        G_after = get_graph(db_path=self.db_path)
        self.assertEqual(G_after.number_of_nodes(), initial_count + 1)
        self.assertIn(new_node_id, G_after.nodes)
        node_attrs = G_after.nodes[new_node_id]
        self.assertEqual(node_attrs["type"], "code")
        self.assertEqual(node_attrs["name"], "integration_test_code")
        self.assertEqual(node_attrs["definition"], "A code inserted via API")
        self.assertEqual(node_attrs["tag"], "TestTag")
        self.assertEqual(node_attrs["status"], "draft")

    def test_insert_edge_via_api_reflects_in_graph(self) -> None:
        """Inserting an edge via DuckDB and calling sync_edge() adds it to graph."""
        # Setup: create two nodes
        con = duckdb.connect(str(self.db_path))
        con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status) VALUES (?, ?, ?, ?, ?, ?)",
            [100, "code", "Source", None, None, "draft"],
        )
        con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status) VALUES (?, ?, ?, ?, ?, ?)",
            [101, "code", "Target", None, None, "draft"],
        )
        con.close()
        # Build initial graph
        get_graph(db_path=self.db_path)
        # Insert edge
        con = duckdb.connect(str(self.db_path))
        con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type, metadata_json) VALUES (?, ?, ?, ?)",
            [100, 101, "derived-from", '{"step": 1}'],
        )
        con.close()
        # Sync edge
        sync_edge(100, 101, "derived-from", db_path=self.db_path)
        # Verify
        G = get_graph(db_path=self.db_path)
        self.assertTrue(G.has_edge(100, 101))
        edge_attrs = G.edges[100, 101]
        self.assertEqual(edge_attrs["type"], "derived-from")
        self.assertEqual(edge_attrs["metadata"], {"step": 1})

    def test_rebuild_graph_after_bulk_insert(self) -> None:
        """rebuild_graph() reflects bulk node/edge insertions correctly."""
        # Insert initial 5 nodes
        con = duckdb.connect(str(self.db_path))
        for i in range(5):
            con.execute(
                "INSERT INTO nodes (type, name, definition, tag, status) VALUES (?, ?, ?, ?, ?)",
                ["code", f"InitCode{i}", None, None, "draft"],
            )
        con.close()
        # Build graph
        G1 = get_graph(db_path=self.db_path)
        self.assertEqual(G1.number_of_nodes(), 5)
        # Bulk insert 10 more nodes
        con = duckdb.connect(str(self.db_path))
        con.executemany(
            "INSERT INTO nodes (type, name, definition, tag, status) VALUES (?, ?, ?, ?, ?)",
            [("code", f"AddedCode{j}", None, None, "draft") for j in range(5, 15)],
        )
        con.close()
        # Stale graph still shows 5
        G2 = get_graph(db_path=self.db_path)
        self.assertEqual(G2.number_of_nodes(), 5)
        # Rebuild
        G3 = rebuild_graph(db_path=self.db_path)
        self.assertEqual(G3.number_of_nodes(), 15)


if __name__ == "__main__":
    unittest.main()
