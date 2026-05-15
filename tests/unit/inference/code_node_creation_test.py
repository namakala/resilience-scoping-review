"""Integration-style tests for inference/code_node_creation.py."""

# flake8: noqa: E402
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import duckdb
from graph import get_node, get_nodes_by_type_and_tag
from graph.node_crud import create_node as _real_create_node
from inference.code_node_creation import create_code_nodes
from inference.inference_status_crud import init_inference_status_table
from inference.inference_status_types import ENTITY_CODE, STAGE_CODE
from inference.parsing import CodeInference
from persistence.duckdb_init import initialize_database


class TestCreateCodeNodes(unittest.TestCase):
    """Integration tests for create_code_nodes()."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))
        init_inference_status_table(self.con)
        import graph.singleton as singleton

        singleton._graph = None

    def tearDown(self) -> None:
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.singleton as singleton

        singleton._graph = None

    def _make_code(self, exemplar_id, code_name, definition, tag="T1") -> CodeInference:
        return CodeInference(
            exemplar_id=exemplar_id,
            code_name=code_name,
            definition=definition,
            supporting_quote="quote",
            related_existing_codes=[],
            tag=tag,
        )

    # ── Basic creation ────────────────────────────────────────────────────

    def test_single_code_creates_node_and_edges(self):
        """One CodeInference creates one code node + contains edge + exemplar node."""
        codes = [self._make_code("1", "Barrier", "def")]
        node_ids = create_code_nodes(self.con, codes, db_path=self.db_path)
        self.assertEqual(len(node_ids), 1)

        nid = node_ids[0]
        node = get_node(nid, db_path=self.db_path)
        self.assertEqual(node["type"], "code")
        self.assertEqual(node["name"], "Barrier")
        self.assertEqual(node["definition"], "def")
        self.assertEqual(node["tag"], "T1")
        self.assertEqual(node["status"], "draft")
        self.assertIsInstance(node["data_json"], dict)
        self.assertEqual(node["data_json"]["exemplar_ids"], ["1"])
        self.assertEqual(node["data_json"]["supporting_quotes"], {"1": "quote"})

        # contains edge exists
        edges = self.con.execute(
            "SELECT source_id, target_id, edge_type FROM edges"
        ).fetchall()
        contains = [e for e in edges if e[2] == "contains"]
        self.assertEqual(len(contains), 1)
        self.assertEqual(contains[0][0], nid)

        # exemplar node was auto-created
        exemplars = get_nodes_by_type_and_tag("exemplar", "T1", db_path=self.db_path)
        self.assertEqual(len(exemplars), 1)

    def test_multiple_codes_same_tag(self):
        """Three CodeInference items yield three code nodes."""
        codes = [
            self._make_code("1", "A", "def A"),
            self._make_code("2", "B", "def B"),
            self._make_code("3", "C", "def C"),
        ]
        node_ids = create_code_nodes(self.con, codes, db_path=self.db_path)
        self.assertEqual(len(node_ids), 3)

        nodes = get_nodes_by_type_and_tag("code", "T1", db_path=self.db_path)
        self.assertEqual(len(nodes), 3)

    def test_empty_codes_returns_empty(self):
        """Empty input returns empty list, no DB writes."""
        result = create_code_nodes(self.con, [], db_path=self.db_path)
        self.assertEqual(result, [])
        count = self.con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self.assertEqual(count, 0)

    # ── Derived-from chaining ─────────────────────────────────────────────

    def test_derived_from_chain_on_re_inference(self):
        """Re-inference creates derived-from edge old→new."""
        codes1 = [self._make_code("1", "V1", "first")]
        ids1 = create_code_nodes(self.con, codes1, db_path=self.db_path)

        codes2 = [self._make_code("1", "V2", "second")]
        ids2 = create_code_nodes(self.con, codes2, db_path=self.db_path)

        edges = self.con.execute(
            "SELECT source_id, target_id, edge_type FROM edges "
            "WHERE edge_type = 'derived-from'"
        ).fetchall()
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0][0], ids1[0])  # old → new
        self.assertEqual(edges[0][1], ids2[0])

    def test_derived_from_chain_multiple_re_inferences(self):
        """Three inference runs: v1→v2 and v2→v3."""
        ids = []
        for version in ("V1", "V2", "V3"):
            ids.append(
                create_code_nodes(
                    self.con,
                    [self._make_code("1", version, f"def {version}")],
                    db_path=self.db_path,
                )[0]
            )

        edges = self.con.execute(
            "SELECT source_id, target_id, edge_type FROM edges "
            "WHERE edge_type = 'derived-from' ORDER BY source_id"
        ).fetchall()
        self.assertEqual(len(edges), 2)
        self.assertEqual(edges[0][0], ids[0])
        self.assertEqual(edges[0][1], ids[1])
        self.assertEqual(edges[1][0], ids[1])
        self.assertEqual(edges[1][1], ids[2])

    # ── Duplicate name handling ───────────────────────────────────────────

    def test_duplicate_code_names_allowed(self):
        """Two codes with same name both created (one suffixed)."""
        codes = [
            self._make_code("1", "SameName", "def"),
            self._make_code("2", "SameName", "def"),
        ]
        node_ids = create_code_nodes(self.con, codes, db_path=self.db_path)
        self.assertEqual(len(node_ids), 2)

        nodes = get_nodes_by_type_and_tag("code", "T1", db_path=self.db_path)
        names = {n["name"] for n in nodes}
        self.assertIn("SameName", names)
        self.assertIn("SameName_1", names)

    def test_duplicate_across_calls_handled(self):
        """Same name across separate calls creates suffixed second node."""
        create_code_nodes(
            self.con,
            [self._make_code("1", "Alpha", "first")],
            db_path=self.db_path,
        )
        create_code_nodes(
            self.con,
            [self._make_code("2", "Alpha", "second")],
            db_path=self.db_path,
        )
        nodes = get_nodes_by_type_and_tag("code", "T1", db_path=self.db_path)
        self.assertEqual(len(nodes), 2)
        names = {n["name"] for n in nodes}
        self.assertIn("Alpha", names)
        self.assertIn("Alpha_1", names)

    # ── Transactional rollback ────────────────────────────────────────────

    def test_transactional_rollback_on_error(self):
        """If an error occurs inside graph_transaction, nothing is committed."""
        codes = [
            self._make_code("1", "Good", "def"),
            self._make_code("2", "Bad", "def"),
        ]
        call_count = [0]

        def _side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise ValueError("Simulated failure inside transaction")
            return _real_create_node(*args, **kwargs)

        with patch(
            "inference.code_node_creation.create_node",
            side_effect=_side_effect,
        ):
            with self.assertRaises(ValueError):
                create_code_nodes(self.con, codes, db_path=self.db_path)

        # No code nodes should remain in the DB
        code_nodes = get_nodes_by_type_and_tag("code", "T1", db_path=self.db_path)
        self.assertEqual(len(code_nodes), 0)

        # No contains edges
        edges = self.con.execute(
            "SELECT COUNT(*) FROM edges WHERE edge_type = 'contains'"
        ).fetchone()[0]
        self.assertEqual(edges, 0)

        # Exemplar nodes (created before transaction) should still exist
        exemplars = get_nodes_by_type_and_tag("exemplar", "T1", db_path=self.db_path)
        self.assertEqual(len(exemplars), 2)

    # ── Queryability ──────────────────────────────────────────────────────

    def test_nodes_queryable_by_tag(self):
        """get_nodes_by_type_and_tag('code', tag) returns new nodes."""
        codes = [
            self._make_code("1", "Q1", "q1"),
            self._make_code("2", "Q2", "q2"),
        ]
        create_code_nodes(self.con, codes, db_path=self.db_path)

        nodes = get_nodes_by_type_and_tag("code", "T1", db_path=self.db_path)
        self.assertEqual(len(nodes), 2)

    # ── Inference status ──────────────────────────────────────────────────

    def test_code_inference_status_generated(self):
        """Each new code entity has inference_status=generated."""
        codes = [
            self._make_code("1", "S1", "s1"),
            self._make_code("2", "S2", "s2"),
        ]
        node_ids = create_code_nodes(self.con, codes, db_path=self.db_path)

        for nid in node_ids:
            row = self.con.execute(
                "SELECT status FROM inference_status "
                "WHERE entity_id = ? AND entity_type = ? AND stage = ?",
                [str(nid), ENTITY_CODE, STAGE_CODE],
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "generated")

    # ── Tag validation ────────────────────────────────────────────────────

    def test_codes_without_tag_raises(self):
        """CodeInference with empty tag raises ValueError."""
        codes = [
            CodeInference(
                exemplar_id="1",
                code_name="NoTag",
                definition="def",
                supporting_quote="q",
            )
        ]
        with self.assertRaises(ValueError) as cm:
            create_code_nodes(self.con, codes, db_path=self.db_path)
        self.assertIn("tag", str(cm.exception).lower())

    # ── Multiple tags ─────────────────────────────────────────────────────

    def test_codes_with_different_tags(self):
        """Codes with different tags are grouped and created under correct tags."""
        codes = [
            self._make_code("1", "C1", "d1", tag="Tag.A"),
            self._make_code("2", "C2", "d2", tag="Tag.B"),
            self._make_code("3", "C3", "d3", tag="Tag.A"),
        ]
        node_ids = create_code_nodes(self.con, codes, db_path=self.db_path)
        self.assertEqual(len(node_ids), 3)

        tag_a_nodes = get_nodes_by_type_and_tag("code", "Tag.A", db_path=self.db_path)
        tag_b_nodes = get_nodes_by_type_and_tag("code", "Tag.B", db_path=self.db_path)
        self.assertEqual(len(tag_a_nodes), 2)
        self.assertEqual(len(tag_b_nodes), 1)

    # ── Performance ───────────────────────────────────────────────────────

    def test_performance_100_nodes(self):
        """Creating 100 code nodes completes in <1 second."""
        import time

        codes = [
            self._make_code(str(i), f"Code_{i}", f"def {i}", tag="Perf.Test")
            for i in range(100)
        ]
        start = time.time()
        node_ids = create_code_nodes(self.con, codes, db_path=self.db_path)
        elapsed = time.time() - start
        self.assertEqual(len(node_ids), 100)
        self.assertLess(
            elapsed,
            1.0,
            f"Creating 100 code nodes took {elapsed:.3f}s (expected <1s)",
        )


if __name__ == "__main__":
    unittest.main()
