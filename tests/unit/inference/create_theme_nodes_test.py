"""Integration tests for inference/create_theme_nodes.py.

Uses a real DuckDB database with initialized graph schema,
creating theme nodes and verifying edges, status, and error handling.
"""

# flake8: noqa: E402
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src" / "python"))

import duckdb
from graph import get_node
from graph.exceptions import ForeignKeyError
from graph.node_crud import create_node
from inference.create_theme_nodes import create_theme_nodes
from inference.inference_status_crud import init_inference_status_table
from inference.inference_status_queries import get_status
from inference.inference_status_types import ENTITY_THEME, GENERATED, STAGE_THEME
from inference.parsing import ThemeInference
from persistence.duckdb_init import initialize_database


class TestCreateThemeNodes(unittest.TestCase):
    """Integration tests for create_theme_nodes()."""

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

    def _precreate_code_nodes(self) -> dict[int, int]:
        """Create prerequisite code nodes; return {source_id: node_id}."""
        ids = {}
        for sid in [1, 2, 3]:
            nid = create_node(
                node_type="code",
                name=f"Code{sid}",
                definition=f"Definition for code {sid}",
                tag="T1",
                status="approved",
                data_json={"exemplar_ids": [str(sid)]},
                db_path=self.db_path,
            )
            ids[sid] = nid
        return ids

    def _make_theme_inference_item(
        self, name: str, code_ids: list[str], narrative: str = "narrative"
    ) -> ThemeInference:
        return ThemeInference(theme_name=name, narrative=narrative, code_ids=code_ids)

    # ── Basic creation ────────────────────────────────────────────────────

    def test_single_theme_creates_node_and_edge(self):
        code_map = self._precreate_code_nodes()
        themes = [
            self._make_theme_inference_item("T1", [str(code_map[1]), str(code_map[2])])
        ]
        node_ids = create_theme_nodes(self.con, themes, tag="T1", db_path=self.db_path)
        self.assertEqual(len(node_ids), 1)

        nid = node_ids[0]
        node = get_node(nid, db_path=self.db_path)
        self.assertEqual(node["type"], "theme")
        self.assertEqual(node["name"], "T1")
        self.assertEqual(node["definition"], "narrative")
        self.assertEqual(node["tag"], "T1")
        self.assertEqual(node["status"], "draft")
        self.assertIsInstance(node["data_json"], dict)
        self.assertEqual(
            node["data_json"]["code_ids"],
            [str(code_map[1]), str(code_map[2])],
        )

        composed_of_edges = self.con.execute(
            "SELECT source_id, target_id, edge_type FROM edges WHERE edge_type = 'composed-of'"
        ).fetchall()
        self.assertEqual(len(composed_of_edges), 2)
        for src, tgt, etype in composed_of_edges:
            self.assertEqual(src, nid)
            self.assertEqual(etype, "composed-of")
            self.assertIn(tgt, (code_map[1], code_map[2]))

    def test_multiple_themes(self):
        code_map = self._precreate_code_nodes()
        themes = [
            self._make_theme_inference_item("A", [str(code_map[1])]),
            self._make_theme_inference_item("B", [str(code_map[2]), str(code_map[3])]),
        ]
        node_ids = create_theme_nodes(self.con, themes, tag="T1", db_path=self.db_path)
        self.assertEqual(len(node_ids), 2)

        nodes = [get_node(nid, db_path=self.db_path) for nid in node_ids]
        names = {n["name"] for n in nodes}
        self.assertSetEqual(names, {"A", "B"})

    # ── Edge cases ────────────────────────────────────────────────────────

    def test_empty_themes_returns_empty(self):
        result = create_theme_nodes(self.con, [], tag="T1", db_path=self.db_path)
        self.assertEqual(result, [])

    def test_empty_tag_raises(self):
        themes = [self._make_theme_inference_item("A", ["1"])]
        with self.assertRaises(ValueError):
            create_theme_nodes(self.con, themes, tag="", db_path=self.db_path)

    def test_empty_theme_name_raises(self):
        themes = [ThemeInference(theme_name="", narrative="n", code_ids=["1"])]
        with self.assertRaises(ValueError):
            create_theme_nodes(self.con, themes, tag="T1", db_path=self.db_path)

    def test_invalid_code_id_raises_foreignkey(self):
        """Non-existent code_id causes ForeignKeyError + transaction rollback."""
        themes = [self._make_theme_inference_item("A", ["999999"])]
        with self.assertRaises(ForeignKeyError):
            create_theme_nodes(self.con, themes, tag="T1", db_path=self.db_path)
        # Transaction rolled back: no theme node or edge was created
        nodes = self.con.execute(
            "SELECT COUNT(*) FROM nodes WHERE type = 'theme'"
        ).fetchone()
        self.assertEqual(nodes[0], 0)

    # ── Inference status ──────────────────────────────────────────────────

    def test_inference_status_set_to_generated(self):
        code_map = self._precreate_code_nodes()
        themes = [self._make_theme_inference_item("A", [str(code_map[1])])]
        node_ids = create_theme_nodes(self.con, themes, tag="T1", db_path=self.db_path)

        status = get_status(self.con, str(node_ids[0]), ENTITY_THEME, STAGE_THEME)
        self.assertIsNotNone(status)
        self.assertEqual(status["status"], GENERATED)

    def test_multiple_nodes_all_have_status(self):
        code_map = self._precreate_code_nodes()
        themes = [
            self._make_theme_inference_item("A", [str(code_map[1])]),
            self._make_theme_inference_item("B", [str(code_map[2])]),
        ]
        node_ids = create_theme_nodes(self.con, themes, tag="T1", db_path=self.db_path)

        for nid in node_ids:
            status = get_status(self.con, str(nid), ENTITY_THEME, STAGE_THEME)
            self.assertIsNotNone(status)
            self.assertEqual(status["status"], GENERATED)


if __name__ == "__main__":
    unittest.main()
