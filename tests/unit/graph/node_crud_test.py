"""Unit tests for node CRUD operations (create_node).

Test coverage:
- Successful node creation with all fields
- Duplicate (type, name) rejection
- JSON data_json serialization/deserialization round-trip
- NetworkX graph synchronization (node appears immediately)
- Atomicity guarantees (integration with transaction manager)
- Status and type variants (code, theme, interpretation, tag)
"""

# flake8: noqa: E402
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

# Add src/python to sys.path for imports
sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import duckdb
from graph import create_node, get_graph, rebuild_graph
from persistence.duckdb_connection import get_connection
from persistence.duckdb_init import initialize_database


class TestCreateNode(unittest.TestCase):
    """Tests for create_node API."""

    def setUp(self) -> None:
        """Create temporary database and reset singleton."""
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

    def _query_node(self, node_id: int) -> tuple[Any, ...] | None:
        """Helper: fetch node row from DuckDB."""
        return self.con.execute(  # type: ignore[no-any-return]
            "SELECT type, name, definition, tag, status, data_json FROM nodes WHERE id = ?",
            [node_id],
        ).fetchone()

    def _query_node_data_json(self, node_id: int) -> dict[str, Any] | None:
        """Helper: fetch and deserialize data_json from DuckDB."""
        row = self.con.execute(
            "SELECT data_json FROM nodes WHERE id = ?", [node_id]
        ).fetchone()
        if row and row[0] is not None:
            return cast(dict[str, Any], json.loads(row[0]))
        return None

    def test_create_node_basic(self) -> None:
        """create_node inserts a row and returns a valid integer ID."""
        node_id = create_node(
            node_type="code",
            name="Test Code",
            definition="A test code definition",
            tag="Test.Tag",
            status="draft",
            db_path=self.db_path,
        )
        self.assertIsInstance(node_id, int)
        self.assertGreater(node_id, 0)

        row = self._query_node(node_id)
        self.assertIsNotNone(row)
        assert row is not None
        type_, name, definition, tag, status, data_json_str = row
        self.assertEqual(type_, "code")
        self.assertEqual(name, "Test Code")
        self.assertEqual(definition, "A test code definition")
        self.assertEqual(tag, "Test.Tag")
        self.assertEqual(status, "draft")
        self.assertIsNone(data_json_str)

    def test_create_node_with_data_json(self) -> None:
        """data_json dict is serialized and stored correctly."""
        payload = {
            "exemplar_count": 3,
            "keywords": ["foo", "bar"],
            "nested": {"a": 1, "b": None},
        }
        node_id = create_node(
            node_type="theme",
            name="Access Issues",
            definition="Theme narrative",
            tag="Problem.Cause",
            status="draft",
            data_json=payload,
            db_path=self.db_path,
        )

        stored = self._query_node_data_json(node_id)
        self.assertEqual(stored, payload)

        G = get_graph(db_path=self.db_path)
        self.assertIn(node_id, G.nodes)
        self.assertEqual(G.nodes[node_id]["data_json"], payload)

    def test_create_node_all_node_types(self) -> None:
        """create_node works for all node types with appropriate statuses."""
        test_cases = [
            ("code", "C1", "def", "TagX", "draft"),
            ("theme", "T1", "narrative", "TagY", "approved"),
            ("interpretation", "I1", "synthesis", "TagZ", "draft"),
            ("tag", "RootTag", "ontology root", None, "immutable"),
        ]
        for node_type, name, definition, tag, status in test_cases:
            nid = create_node(
                node_type=node_type,
                name=name,
                definition=definition,
                tag=tag,
                status=status,
                db_path=self.db_path,
            )
            row = self._query_node(nid)
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row[0], node_type)
            self.assertEqual(row[1], name)
            self.assertEqual(row[4], status)

    def test_duplicate_rejection_same_typeAndName(self) -> None:
        """Duplicate (type, name) raises ValueError; DB unchanged."""
        create_node(
            node_type="code",
            name="Barrier",
            definition="First",
            tag="T1",
            status="draft",
            db_path=self.db_path,
        )
        with self.assertRaises(ValueError) as cm:
            create_node(
                node_type="code",
                name="Barrier",
                definition="Second",
                tag="T2",
                status="draft",
                db_path=self.db_path,
            )
        self.assertIn("already exists", str(cm.exception))

        count_row = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()
        self.assertEqual(count_row[0], 1)

    def test_duplicate_different_type_allowed(self) -> None:
        """Same name with different node_type is allowed."""
        create_node(
            node_type="code",
            name="Focus",
            definition="Code def",
            tag="T1",
            status="draft",
            db_path=self.db_path,
        )
        nid2 = create_node(
            node_type="theme",
            name="Focus",
            definition="Theme def",
            tag="T1",
            status="draft",
            db_path=self.db_path,
        )
        self.assertIsInstance(nid2, int)
        count_row = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()
        self.assertEqual(count_row[0], 2)

    def test_duplicate_different_name_allowed(self) -> None:
        """Same type with different name is allowed."""
        create_node(
            node_type="code",
            name="Alpha",
            definition="First",
            tag="T1",
            status="draft",
            db_path=self.db_path,
        )
        nid2 = create_node(
            node_type="code",
            name="Beta",
            definition="Second",
            tag="T1",
            status="draft",
            db_path=self.db_path,
        )
        self.assertIsInstance(nid2, int)
        count_row = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()
        self.assertEqual(count_row[0], 2)

    def test_graph_reflects_insert_immediately(self) -> None:
        """After create_node, in-memory graph contains the new node."""
        G1 = get_graph(db_path=self.db_path)
        self.assertEqual(G1.number_of_nodes(), 0)

        nid = create_node(
            node_type="code",
            name="Immediate",
            definition="Visible now",
            tag="Visible",
            status="draft",
            db_path=self.db_path,
        )

        G2 = get_graph(db_path=self.db_path)
        self.assertIn(nid, G2.nodes)
        attrs = G2.nodes[nid]
        self.assertEqual(attrs["type"], "code")
        self.assertEqual(attrs["name"], "Immediate")
        self.assertEqual(attrs["definition"], "Visible now")
        self.assertEqual(attrs["tag"], "Visible")
        self.assertEqual(attrs["status"], "draft")
        self.assertEqual(attrs["data_json"], None)

    def test_create_node_with_none_data_json(self) -> None:
        """data_json=None is stored as NULL in DB and None in graph."""
        nid = create_node(
            node_type="code",
            name="NoExtra",
            definition="No data",
            tag="NoneTest",
            status="draft",
            data_json=None,
            db_path=self.db_path,
        )
        row = self.con.execute(
            "SELECT data_json FROM nodes WHERE id = ?", [nid]
        ).fetchone()
        self.assertIsNone(row[0])
        G = get_graph(db_path=self.db_path)
        self.assertIsNone(G.nodes[nid]["data_json"])

    def test_created_at_is_populated(self) -> None:
        """DuckDB DEFAULT CURRENT_TIMESTAMP sets created_at."""
        nid = create_node(
            node_type="code",
            name="Timestamped",
            definition="Check time",
            tag="Time",
            status="draft",
            db_path=self.db_path,
        )
        row = self.con.execute(
            "SELECT created_at FROM nodes WHERE id = ?", [nid]
        ).fetchone()
        self.assertIsNotNone(row)
        assert row is not None
        self.assertIsNotNone(row[0])
        self.assertGreater(len(str(row[0])), 0)

    def test_invalid_json_in_data_json_raises(self) -> None:
        """Non-JSON-serializable data_json raises ValueError before DB write."""
        bad_data = {"dt": complex(1, 2)}
        with self.assertRaises(ValueError) as cm:
            create_node(
                node_type="code",
                name="BadJSON",
                definition="won't reach DB",
                tag="Invalid",
                status="draft",
                data_json=bad_data,
                db_path=self.db_path,
            )
        self.assertIn("JSON-serializable", str(cm.exception))
        count = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(count, 0)


class TestCreateNodeAtomicity(unittest.TestCase):
    """Atomicity tests: DuckDB and NetworkX succeed or fail together.

    These tests depend on Feature 16's graph_transaction context manager.
    If not yet implemented, these tests may be skipped or marked expectedFailure.
    """

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))
        import graph.singleton as singleton

        singleton._graph = None

    def tearDown(self) -> None:
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.singleton as singleton

        singleton._graph = None

    def test_atomicity_partial_failure_rollback(self) -> None:
        """If an exception occurs mid-transaction, neither DB nor graph changes persist."""
        try:
            from graph.transactions import graph_transaction
        except ImportError:
            self.skipTest("Feature 16 (transactions) not yet implemented")

        with self.assertRaises(ValueError):
            with graph_transaction(db_path=self.db_path):
                nid1 = create_node(
                    node_type="code",
                    name="Node1",
                    definition="First",
                    tag="T",
                    status="draft",
                    db_path=self.db_path,
                )
                create_node(
                    node_type="code",
                    name="Node1",
                    definition="Second",
                    tag="T",
                    status="draft",
                    db_path=self.db_path,
                )

        count = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(count, 0)
        G = get_graph(db_path=self.db_path)
        self.assertEqual(G.number_of_nodes(), 0)


if __name__ == "__main__":
    unittest.main()
