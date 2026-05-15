"""Unit tests for graph_transaction context manager.

Test coverage:
- Successful batch commits node + edge atomically
- Exception mid-batch rolls back both DuckDB and NetworkX
- Nested transaction raises GraphTransactionError
- Empty transaction block is a no-op
- create_edges inside transaction uses shared connection
- Graph not yet initialized before transaction
- Deadlock retry on commit
"""

# flake8: noqa: E402
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Add src/python to sys.path for imports
sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import duckdb
from graph import (
    GraphTransactionError,
    create_edge,
    create_edges,
    create_node,
    get_graph,
    graph_transaction,
    rebuild_graph,
)
from graph.transactions import get_active_connection, is_in_transaction
from persistence.duckdb_init import initialize_database


class TestGraphTransaction(unittest.TestCase):
    """Tests for the graph_transaction context manager."""

    def setUp(self) -> None:
        """Create temp database and reset singleton."""
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))
        import graph.singleton as singleton

        singleton._graph = None

    def tearDown(self) -> None:
        """Clean up temp files and reset singleton."""
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.singleton as singleton

        singleton._graph = None

    def test_successful_transaction(self) -> None:
        """Multiple operations inside a transaction commit atomically."""
        with graph_transaction(db_path=self.db_path):
            nid1 = create_node(
                node_type="code",
                name="TxNode1",
                definition="First node in tx",
                tag="Test",
                status="draft",
                db_path=self.db_path,
            )
            nid2 = create_node(
                node_type="code",
                name="TxNode2",
                definition="Second node in tx",
                tag="Test",
                status="draft",
                db_path=self.db_path,
            )
            create_edge(
                source_id=nid1,
                target_id=nid2,
                edge_type="contains",
                db_path=self.db_path,
            )

        # Both nodes and edge should exist after commit
        count_nodes = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(count_nodes, 2)

        count_edges = self.con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        self.assertEqual(count_edges, 1)

        G = get_graph(db_path=self.db_path)
        self.assertEqual(G.number_of_nodes(), 2)
        self.assertEqual(G.number_of_edges(), 1)

    def test_rollback_on_exception(self) -> None:
        """Exception inside transaction rolls back both stores."""
        with self.assertRaises(RuntimeError):
            with graph_transaction(db_path=self.db_path):
                create_node(
                    node_type="code",
                    name="RollbackMe",
                    definition="Should disappear",
                    tag="Test",
                    status="draft",
                    db_path=self.db_path,
                )
                raise RuntimeError("Simulated failure")

        count_nodes = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(count_nodes, 0, "DB should have no nodes after rollback")

        G = get_graph(db_path=self.db_path)
        self.assertEqual(
            G.number_of_nodes(), 0, "Graph should have no nodes after rollback"
        )

    def test_rollback_after_duplicate_node(self) -> None:
        """Duplicate node raises ValueError; transaction rolls back."""
        with self.assertRaises(ValueError):
            with graph_transaction(db_path=self.db_path):
                create_node(
                    node_type="code",
                    name="DupTest",
                    definition="First",
                    tag="T",
                    status="draft",
                    db_path=self.db_path,
                )
                # Duplicate (type, name) pair raises ValueError
                create_node(
                    node_type="code",
                    name="DupTest",
                    definition="Second",
                    tag="T",
                    status="draft",
                    db_path=self.db_path,
                )

        count_nodes = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(count_nodes, 0, "No rows should remain after rollback")

        G = get_graph(db_path=self.db_path)
        self.assertEqual(G.number_of_nodes(), 0)

    def test_nested_transaction_raises_error(self) -> None:
        """Nesting graph_transaction raises GraphTransactionError."""
        with graph_transaction(db_path=self.db_path):
            with self.assertRaises(GraphTransactionError):
                with graph_transaction(db_path=self.db_path):
                    create_node(
                        node_type="code",
                        name="Nested",
                        definition="Should not appear",
                        tag="Test",
                        status="draft",
                        db_path=self.db_path,
                    )

        # Outer transaction should still commit (first node)
        count_nodes = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(count_nodes, 0)

    def test_empty_transaction(self) -> None:
        """Transaction block with no operations is a no-op."""
        with graph_transaction(db_path=self.db_path):
            pass

        count_nodes = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(count_nodes, 0)

        G = get_graph(db_path=self.db_path)
        self.assertEqual(G.number_of_nodes(), 0)

    def test_rollback_preserves_pre_tx_state(self) -> None:
        """Graph state from before transaction is preserved after rollback."""
        # Create a node outside any transaction
        survivor = create_node(
            node_type="code",
            name="Survivor",
            definition="Exists before tx",
            tag="Pre",
            status="draft",
            db_path=self.db_path,
        )
        self.con.execute(
            "UPDATE nodes SET name = 'SurvivorPre' WHERE id = ?",
            [survivor],
        )

        # Roll back transaction that adds a node
        with self.assertRaises(RuntimeError):
            with graph_transaction(db_path=self.db_path):
                create_node(
                    node_type="theme",
                    name="Casualty",
                    definition="Dies with tx",
                    tag="Post",
                    status="draft",
                    db_path=self.db_path,
                )
                raise RuntimeError("Rollback now")

        # The survivor node should still exist
        pre_row = self.con.execute(
            "SELECT name FROM nodes WHERE id = ?", [survivor]
        ).fetchone()
        self.assertIsNotNone(pre_row)
        # DB was rolled back to state at BEGIN TRANSACTION
        # The UPDATE before the tx is preserved (committed)
        self.assertEqual(pre_row[0], "SurvivorPre")

        # The casualty should not exist
        count_nodes = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(count_nodes, 1)

        G = get_graph(db_path=self.db_path)
        self.assertEqual(G.number_of_nodes(), 1)
        self.assertIn(survivor, G.nodes)

    def test_create_edges_inside_transaction(self) -> None:
        """create_edges inside tx uses shared connection, no inner tx."""
        nid1 = create_node(
            node_type="code",
            name="ESrc",
            definition="Edge src",
            tag="Test",
            status="draft",
            db_path=self.db_path,
        )
        nid2 = create_node(
            node_type="code",
            name="ETgt",
            definition="Edge tgt",
            tag="Test",
            status="draft",
            db_path=self.db_path,
        )

        with graph_transaction(db_path=self.db_path):
            create_edges(
                [
                    (nid1, nid2, "contains", None),
                ],
                db_path=self.db_path,
            )

        count_edges = self.con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        self.assertEqual(count_edges, 1)

        G = get_graph(db_path=self.db_path)
        self.assertTrue(G.has_edge(nid1, nid2))

    def test_create_edges_inside_transaction_rollback(self) -> None:
        """create_edges inside a failing tx is rolled back."""
        nid1 = create_node(
            node_type="code",
            name="RollSrc",
            definition="Rollback src",
            tag="Test",
            status="draft",
            db_path=self.db_path,
        )
        nid2 = create_node(
            node_type="code",
            name="RollTgt",
            definition="Rollback tgt",
            tag="Test",
            status="draft",
            db_path=self.db_path,
        )

        with self.assertRaises(RuntimeError):
            with graph_transaction(db_path=self.db_path):
                create_edges(
                    [
                        (nid1, nid2, "contains", None),
                    ],
                    db_path=self.db_path,
                )
                raise RuntimeError("Rollback edges tx")

        count_edges = self.con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        self.assertEqual(count_edges, 0)

        G = get_graph(db_path=self.db_path)
        self.assertFalse(G.has_edge(nid1, nid2))

    def test_graph_built_lazily_inside_transaction(self) -> None:
        """Transaction works when graph is not yet initialized."""
        with graph_transaction(db_path=self.db_path):
            nid = create_node(
                node_type="code",
                name="LazyInit",
                definition="Built inside tx",
                tag="Test",
                status="draft",
                db_path=self.db_path,
            )
            self.assertIsInstance(nid, int)
            self.assertGreater(nid, 0)

        count_nodes = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(count_nodes, 1)

    def test_is_in_transaction_inside_block(self) -> None:
        """is_in_transaction() returns True inside the block."""
        self.assertFalse(is_in_transaction())
        with graph_transaction(db_path=self.db_path):
            self.assertTrue(is_in_transaction())
            self.assertIsNotNone(get_active_connection())
        self.assertFalse(is_in_transaction())

    def test_multiple_nodes_and_edges_atomic(self) -> None:
        """Mixed node and edge operations commit atomically."""
        with graph_transaction(db_path=self.db_path):
            nids = []
            for i in range(3):
                nid = create_node(
                    node_type="code",
                    name=f"Batch_{i}",
                    definition=f"Node {i}",
                    tag="Batch",
                    status="draft",
                    db_path=self.db_path,
                )
                nids.append(nid)
            # Fully connected: chain edges
            for i in range(len(nids) - 1):
                create_edge(
                    source_id=nids[i],
                    target_id=nids[i + 1],
                    edge_type="derived-from",
                    db_path=self.db_path,
                )

        count_nodes = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(count_nodes, 3)
        count_edges = self.con.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        self.assertEqual(count_edges, 2)

    def test_deadlock_retry_on_commit(self) -> None:
        """Commit retries once on deadlock error."""
        # Create a node first (outside tx)
        nid = create_node(
            node_type="code",
            name="DeadlockTest",
            definition="Node for deadlock test",
            tag="Test",
            status="draft",
            db_path=self.db_path,
        )

        call_count = [0]

        def _mock_execute(self_, query, *args, **kwargs):
            if "COMMIT" in str(query).upper():
                call_count[0] += 1
                if call_count[0] == 1:
                    raise duckdb.Error(
                        "deadlock detected: lock timeout",
                    )
            return self_.original_execute(query, *args, **kwargs)

        # Patch execute on the transaction connection
        original_execute = duckdb.DuckDBPyConnection.execute
        duckdb.DuckDBPyConnection.original_execute = original_execute
        duckdb.DuckDBPyConnection.execute = _mock_execute  # type: ignore

        try:
            with graph_transaction(db_path=self.db_path):
                create_node(
                    node_type="code",
                    name="DeadlockChild",
                    definition="Child in retried tx",
                    tag="Test",
                    status="draft",
                    db_path=self.db_path,
                )

            # Should have succeeded after retry
            count_nodes = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            self.assertEqual(count_nodes, 2)
            self.assertEqual(call_count[0], 2, "COMMIT should have been called twice")
        finally:
            duckdb.DuckDBPyConnection.execute = original_execute


if __name__ == "__main__":
    unittest.main()
