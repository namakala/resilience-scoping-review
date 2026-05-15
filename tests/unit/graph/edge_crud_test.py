"""Unit tests for edge CRUD operations (create_edge, create_edges).

Test coverage:
- Basic edge creation with DuckDB row and NetworkX sync
- Metadata serialization (dict and None)
- Invalid edge_type rejection
- Nonexistent source/target node rejection
- Duplicate edge rejection and merged-node override
- Batch creation atomicity
"""

# flake8: noqa: E402
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

# Add src/python to sys.path for imports
sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import duckdb
from graph import ForeignKeyError, create_edge, create_edges, create_node, get_graph
from persistence.duckdb_connection import get_connection
from persistence.duckdb_init import initialize_database


class TestCreateEdge(unittest.TestCase):
    """Tests for create_edge and create_edges APIs."""

    def setUp(self) -> None:
        """Create temporary database with two seed nodes and reset singleton."""
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))
        import graph.singleton as singleton

        singleton._graph = None

        self.source_id = create_node(
            node_type="code",
            name="Source",
            definition="Source node",
            tag="Test",
            status="draft",
            db_path=self.db_path,
        )
        self.target_id = create_node(
            node_type="code",
            name="Target",
            definition="Target node",
            tag="Test",
            status="draft",
            db_path=self.db_path,
        )

    def tearDown(self) -> None:
        """Clean up temp files and reset singleton."""
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.singleton as singleton

        singleton._graph = None

    def _query_edge(self, source_id, target_id, edge_type):
        return self.con.execute(
            "SELECT source_id, target_id, edge_type, metadata_json FROM edges "
            "WHERE source_id = ? AND target_id = ? AND edge_type = ?",
            [source_id, target_id, edge_type],
        ).fetchone()

    def _count_edges(self):
        row = self.con.execute("SELECT COUNT(*) FROM edges").fetchone()
        return row[0] if row else 0

    def test_create_edge_basic(self) -> None:
        """create_edge inserts a row and adds a NetworkX edge."""
        create_edge(
            source_id=self.source_id,
            target_id=self.target_id,
            edge_type="contains",
            db_path=self.db_path,
        )

        row = self._query_edge(self.source_id, self.target_id, "contains")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row[0], self.source_id)
        self.assertEqual(row[1], self.target_id)
        self.assertEqual(row[2], "contains")
        self.assertIsNone(row[3])

        G = get_graph(db_path=self.db_path)
        self.assertTrue(G.has_edge(self.source_id, self.target_id))
        edge_data = G.get_edge_data(self.source_id, self.target_id)
        self.assertEqual(edge_data["type"], "contains")
        self.assertIsNone(edge_data["metadata"])

    def test_create_edge_with_metadata(self) -> None:
        """metadata_json dict is serialized and stored correctly."""
        payload = {"confidence": 0.95, "source": "HITL", "tags": ["a", "b"]}
        create_edge(
            source_id=self.source_id,
            target_id=self.target_id,
            edge_type="derived-from",
            metadata_json=payload,
            db_path=self.db_path,
        )

        row = self._query_edge(self.source_id, self.target_id, "derived-from")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(json.loads(row[3]), payload)

        G = get_graph(db_path=self.db_path)
        self.assertEqual(
            G.get_edge_data(self.source_id, self.target_id)["metadata"], payload
        )

    def test_create_edge_none_metadata_stored_as_null(self) -> None:
        """metadata_json=None is stored as SQL NULL, not empty dict."""
        create_edge(
            source_id=self.source_id,
            target_id=self.target_id,
            edge_type="neighbor",
            metadata_json=None,
            db_path=self.db_path,
        )

        row = self._query_edge(self.source_id, self.target_id, "neighbor")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertIsNone(row[3])

        G = get_graph(db_path=self.db_path)
        self.assertIsNone(G.get_edge_data(self.source_id, self.target_id)["metadata"])

    def test_create_edge_invalid_type_raises(self) -> None:
        """Invalid edge_type raises ValueError."""
        with self.assertRaises(ValueError) as cm:
            create_edge(
                source_id=self.source_id,
                target_id=self.target_id,
                edge_type="invalid-type",
                db_path=self.db_path,
            )
        self.assertIn("Invalid edge_type", str(cm.exception))
        self.assertEqual(self._count_edges(), 0)

    def test_create_edge_all_edge_types(self) -> None:
        """All six allowed edge types can be created."""
        edge_types = [
            "parent-child",
            "contains",
            "derived-from",
            "composed-of",
            "spans",
            "neighbor",
        ]
        for i, et in enumerate(edge_types):
            src = create_node(
                node_type="code",
                name=f"Src_{i}",
                definition=f"S{i}",
                tag="Test",
                status="draft",
                db_path=self.db_path,
            )
            tgt = create_node(
                node_type="code",
                name=f"Tgt_{i}",
                definition=f"T{i}",
                tag="Test",
                status="draft",
                db_path=self.db_path,
            )
            create_edge(
                source_id=src, target_id=tgt, edge_type=et, db_path=self.db_path
            )

        self.assertEqual(self._count_edges(), 6)

    def test_create_edge_nonexistent_source(self) -> None:
        """Missing source node raises ForeignKeyError."""
        with self.assertRaises(ForeignKeyError) as cm:
            create_edge(
                source_id=99999,
                target_id=self.target_id,
                edge_type="contains",
                db_path=self.db_path,
            )
        self.assertIn("99999", str(cm.exception))
        self.assertEqual(self._count_edges(), 0)

    def test_create_edge_nonexistent_target(self) -> None:
        """Missing target node raises ForeignKeyError."""
        with self.assertRaises(ForeignKeyError) as cm:
            create_edge(
                source_id=self.source_id,
                target_id=99999,
                edge_type="contains",
                db_path=self.db_path,
            )
        self.assertIn("99999", str(cm.exception))
        self.assertEqual(self._count_edges(), 0)

    def test_create_edge_duplicate_raises(self) -> None:
        """Exact duplicate (source, target, type) raises ValueError."""
        create_edge(
            source_id=self.source_id,
            target_id=self.target_id,
            edge_type="contains",
            db_path=self.db_path,
        )
        with self.assertRaises(ValueError) as cm:
            create_edge(
                source_id=self.source_id,
                target_id=self.target_id,
                edge_type="contains",
                db_path=self.db_path,
            )
        self.assertIn("already exists", str(cm.exception))
        self.assertEqual(self._count_edges(), 1)

    def test_create_edge_duplicate_allowed_when_source_merged(self) -> None:
        """Duplicate edge allowed when source node status is 'merged'."""
        self.con.execute(
            "UPDATE nodes SET status = 'merged' WHERE id = ?", [self.source_id]
        )

        create_edge(
            source_id=self.source_id,
            target_id=self.target_id,
            edge_type="contains",
            metadata_json={"original": True},
            db_path=self.db_path,
        )
        create_edge(
            source_id=self.source_id,
            target_id=self.target_id,
            edge_type="contains",
            metadata_json={"updated": True},
            db_path=self.db_path,
        )

        self.assertEqual(self._count_edges(), 1)
        row = self._query_edge(self.source_id, self.target_id, "contains")
        assert row is not None
        self.assertEqual(json.loads(row[3]), {"updated": True})

    def test_create_edge_duplicate_allowed_when_target_merged(self) -> None:
        """Duplicate edge allowed when target node status is 'merged'."""
        self.con.execute(
            "UPDATE nodes SET status = 'merged' WHERE id = ?", [self.target_id]
        )

        create_edge(
            source_id=self.source_id,
            target_id=self.target_id,
            edge_type="parent-child",
            db_path=self.db_path,
        )
        create_edge(
            source_id=self.source_id,
            target_id=self.target_id,
            edge_type="parent-child",
            metadata_json={"recreated": True},
            db_path=self.db_path,
        )

        self.assertEqual(self._count_edges(), 1)
        row = self._query_edge(self.source_id, self.target_id, "parent-child")
        assert row is not None
        self.assertEqual(json.loads(row[3]), {"recreated": True})

    def test_graph_reflects_edge_immediately(self) -> None:
        """After create_edge, in-memory graph contains the edge."""
        G1 = get_graph(db_path=self.db_path)
        self.assertFalse(G1.has_edge(self.source_id, self.target_id))

        create_edge(
            source_id=self.source_id,
            target_id=self.target_id,
            edge_type="composed-of",
            db_path=self.db_path,
        )

        G2 = get_graph(db_path=self.db_path)
        self.assertTrue(G2.has_edge(self.source_id, self.target_id))
        self.assertEqual(
            G2.get_edge_data(self.source_id, self.target_id)["type"], "composed-of"
        )

    def test_create_edge_invalid_metadata_raises(self) -> None:
        """Non-JSON-serializable metadata raises ValueError."""
        with self.assertRaises(ValueError) as cm:
            create_edge(
                source_id=self.source_id,
                target_id=self.target_id,
                edge_type="contains",
                metadata_json={"complex_val": complex(1, 2)},
                db_path=self.db_path,
            )
        self.assertIn("JSON-serializable", str(cm.exception))
        self.assertEqual(self._count_edges(), 0)

    def test_create_edges_basic(self) -> None:
        """create_edges creates multiple edges atomically."""
        n1, n2 = self.source_id, self.target_id
        n3 = create_node(
            node_type="theme",
            name="Third",
            definition="Third node",
            tag="Test",
            status="draft",
            db_path=self.db_path,
        )

        create_edges(
            [
                (n1, n2, "contains", {"order": 1}),
                (n2, n3, "derived-from", {"order": 2}),
                (n1, n3, "neighbor", None),
            ],
            db_path=self.db_path,
        )

        self.assertEqual(self._count_edges(), 3)
        G = get_graph(db_path=self.db_path)
        self.assertTrue(G.has_edge(n1, n2))
        self.assertTrue(G.has_edge(n2, n3))
        self.assertTrue(G.has_edge(n1, n3))

    def test_create_edges_atomic_rollback(self) -> None:
        """If one edge in batch fails, no edges are inserted."""
        n1, n2 = self.source_id, self.target_id
        n3 = create_node(
            node_type="theme",
            name="RollbackThird",
            definition="Third node",
            tag="Test",
            status="draft",
            db_path=self.db_path,
        )

        with self.assertRaises(ValueError):
            create_edges(
                [
                    (n1, n2, "contains", None),
                    (n2, n3, "invalid-type", None),
                    (n1, n3, "neighbor", None),
                ],
                db_path=self.db_path,
            )

        self.assertEqual(self._count_edges(), 0)
        G = get_graph(db_path=self.db_path)
        self.assertEqual(G.number_of_edges(), 0)

    def test_create_edges_empty_list(self) -> None:
        """Empty edge list is a no-op."""
        create_edges([], db_path=self.db_path)
        self.assertEqual(self._count_edges(), 0)

    def test_create_edges_missing_node_rollback(self) -> None:
        """If a node is missing in batch, all edges are rolled back."""
        with self.assertRaises(ForeignKeyError):
            create_edges(
                [
                    (self.source_id, 99999, "contains", None),
                ],
                db_path=self.db_path,
            )

        self.assertEqual(self._count_edges(), 0)


if __name__ == "__main__":
    unittest.main()
