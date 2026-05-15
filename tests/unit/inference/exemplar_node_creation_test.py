"""Tests for inference/exemplar_node_creation.py."""

# flake8: noqa: E402
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import duckdb
from graph import get_node, get_nodes_by_type_and_tag
from inference.exemplar_node_creation import ensure_exemplar_nodes
from persistence.duckdb_init import initialize_database


class TestEnsureExemplarNodes(unittest.TestCase):
    """Tests for ensure_exemplar_nodes()."""

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

    def test_creates_missing_exemplar_nodes(self):
        """Three exemplar IDs yields three graph nodes with correct attributes."""
        eids = {"101", "102", "103"}
        result = ensure_exemplar_nodes(
            self.con, eids, tag="Problem.Cause", db_path=self.db_path
        )
        self.assertEqual(len(result), 3)
        for eid in eids:
            self.assertIn(eid, result)
            nid = result[eid]
            self.assertIsInstance(nid, int)
            self.assertGreater(nid, 0)

            node = get_node(nid, db_path=self.db_path)
            self.assertEqual(node["type"], "exemplar")
            self.assertEqual(node["tag"], "Problem.Cause")
            self.assertEqual(node["status"], "immutable")
            self.assertEqual(node["name"], f"exemplar_{eid}_Problem.Cause")

    def test_returns_correct_map(self):
        """Returned dict maps exemplar_id strings to integer node IDs."""
        eids = {"42"}
        result = ensure_exemplar_nodes(self.con, eids, tag="T1", db_path=self.db_path)
        self.assertEqual(set(result.keys()), {"42"})
        self.assertIsInstance(result["42"], int)

    def test_existing_nodes_reused(self):
        """Calling twice returns the same node IDs and creates no duplicates."""
        eids = {"1", "2"}
        first = ensure_exemplar_nodes(self.con, eids, tag="Tag.A", db_path=self.db_path)
        second = ensure_exemplar_nodes(
            self.con, eids, tag="Tag.A", db_path=self.db_path
        )
        self.assertEqual(first, second)
        count = self.con.execute(
            "SELECT COUNT(*) FROM nodes WHERE type = 'exemplar'"
        ).fetchone()[0]
        self.assertEqual(count, 2)

    def test_empty_ids_returns_empty_map(self):
        """Empty input set returns empty dict, no DB writes."""
        result = ensure_exemplar_nodes(self.con, set(), tag="T1", db_path=self.db_path)
        self.assertEqual(result, {})
        count = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(count, 0)

    def test_nodes_queryable_by_type_and_tag(self):
        """Created exemplar nodes appear in get_nodes_by_type_and_tag."""
        eids = {"7", "8"}
        ensure_exemplar_nodes(self.con, eids, tag="Query.Test", db_path=self.db_path)
        nodes = get_nodes_by_type_and_tag(
            "exemplar", "Query.Test", db_path=self.db_path
        )
        self.assertEqual(len(nodes), 2)

    def test_partial_existing(self):
        """When some exemplar nodes already exist, only missing ones are created."""
        ensure_exemplar_nodes(self.con, {"1", "2"}, tag="T1", db_path=self.db_path)
        result = ensure_exemplar_nodes(
            self.con, {"1", "2", "3"}, tag="T1", db_path=self.db_path
        )
        self.assertEqual(set(result.keys()), {"1", "2", "3"})
        count = self.con.execute(
            "SELECT COUNT(*) FROM nodes WHERE type = 'exemplar'"
        ).fetchone()[0]
        self.assertEqual(count, 3)

    def test_different_tags_isolated(self):
        """Exemplar nodes for different tags do not interfere."""
        r1 = ensure_exemplar_nodes(self.con, {"1"}, tag="Tag.X", db_path=self.db_path)
        r2 = ensure_exemplar_nodes(self.con, {"1"}, tag="Tag.Y", db_path=self.db_path)
        self.assertNotEqual(r1["1"], r2["1"])


if __name__ == "__main__":
    unittest.main()
