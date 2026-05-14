"""Tests for code review HITL action handlers (no questionary mocking).

Tests handle_approve, handle_edit, handle_merge, handle_reject, handle_defer
by calling them directly and verifying DuckDB state.
"""

# flake8: noqa: E402
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import duckdb
from graph.queries import get_node
from hitl.code_review_actions import (
    handle_approve,
    handle_defer,
    handle_edit,
    handle_reject,
)
from hitl.code_review_merge import handle_merge
from inference.inference_status_crud import init_inference_status_table
from persistence.duckdb_init import initialize_database


class TestCodeReviewActions(unittest.TestCase):
    """Direct unit tests for action handlers (no questionary mocking)."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))
        init_inference_status_table(self.con)
        import graph.singleton as singleton

        singleton._graph = None

    def tearDown(self):
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.singleton as singleton

        singleton._graph = None

    # ── Fixtures ─────────────────────────────────────────────────────────

    def _create_code_node(
        self,
        node_id,
        name="TestCode",
        definition="def",
        tag="T1",
        exemplar_ids=None,
        supporting_quotes=None,
        status="draft",
    ):
        if exemplar_ids is None:
            exemplar_ids = [str(node_id)]
        if supporting_quotes is None:
            supporting_quotes = {str(node_id): "quote"}
        dj = json.dumps(
            {
                "exemplar_ids": exemplar_ids,
                "supporting_quotes": supporting_quotes,
                "related_existing_codes": [],
            }
        )
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'code', ?, ?, ?, ?, ?)",
            [node_id, name, definition, tag, status, dj],
        )
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage, status) "
            "VALUES (?, 'code', 'code', 'generated')",
            [str(node_id)],
        )

    def _create_exemplar_node(self, node_id, exemplar_id):
        dj = json.dumps({"exemplar_id": str(exemplar_id)})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'exemplar', ?, '', 'T1', 'immutable', ?)",
            [node_id, f"ex_{exemplar_id}", dj],
        )

    def _code_dict(self, node_id):
        row = self.con.execute(
            "SELECT id, name, definition, tag, data_json, status "
            "FROM nodes WHERE id = ?",
            [node_id],
        ).fetchone()
        dj = json.loads(row[4]) if row[4] else {}
        return {
            "id": row[0],
            "name": row[1],
            "definition": row[2],
            "tag": row[3],
            "data_json": dj,
            "status": row[5],
        }

    # ── Approve ──────────────────────────────────────────────────────────

    def test_approve_updates_status_and_inference(self):
        self._create_code_node(1)
        code = self._code_dict(1)
        handle_approve(self.con, code, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "approved")

        inf_status = self.con.execute(
            "SELECT status FROM inference_status "
            "WHERE entity_id = '1' AND entity_type = 'code' AND stage = 'code'"
        ).fetchone()[0]
        self.assertEqual(inf_status, "approved")

    # ── Edit ─────────────────────────────────────────────────────────────

    def test_edit_updates_definition_and_resets_status(self):
        self._create_code_node(1)
        code = self._code_dict(1)
        handle_edit(
            self.con, code, db_path=self.db_path, new_definition="new definition"
        )

        node = get_node(1, db_path=self.db_path)
        self.assertEqual(node["definition"], "new definition")
        self.assertEqual(node["status"], "draft")

        inf_status = self.con.execute(
            "SELECT status FROM inference_status "
            "WHERE entity_id = '1' AND entity_type = 'code' AND stage = 'code'"
        ).fetchone()[0]
        self.assertEqual(inf_status, "draft")

    def test_edit_ignores_empty_definition(self):
        self._create_code_node(1, definition="original")
        code = self._code_dict(1)
        handle_edit(self.con, code, db_path=self.db_path, new_definition="")

        node = get_node(1, db_path=self.db_path)
        self.assertEqual(node["definition"], "original")

    def test_edit_ignores_unchanged_definition(self):
        self._create_code_node(1, definition="same")
        code = self._code_dict(1)
        handle_edit(self.con, code, db_path=self.db_path, new_definition="same")

        node = get_node(1, db_path=self.db_path)
        self.assertEqual(node["definition"], "same")

    # ── Merge ────────────────────────────────────────────────────────────

    def test_merge_redirects_edges_and_updates_data_json(self):
        # Code A (source) contains exemplar 10
        self._create_code_node(
            1,
            name="CodeA",
            exemplar_ids=["10"],
            supporting_quotes={"10": "quote A"},
        )
        self._create_exemplar_node(10, "10")
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) "
            "VALUES (1, 10, 'contains')"
        )

        # Code B (target) contains exemplar 11
        self._create_code_node(
            2,
            name="CodeB",
            exemplar_ids=["11"],
            supporting_quotes={"11": "quote B"},
        )
        self._create_exemplar_node(11, "11")
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) "
            "VALUES (2, 11, 'contains')"
        )

        source_code = self._code_dict(1)
        handle_merge(self.con, source_code, target_id=2, db_path=self.db_path)

        # Source status = merged
        src_status = self.con.execute(
            "SELECT status FROM nodes WHERE id = 1"
        ).fetchone()[0]
        self.assertEqual(src_status, "merged")

        # Source data_json: exemplar info cleared
        src_dj = json.loads(
            self.con.execute("SELECT data_json FROM nodes WHERE id = 1").fetchone()[0]
        )
        self.assertNotIn("exemplar_ids", src_dj)
        self.assertNotIn("supporting_quotes", src_dj)

        # Target data_json: merged exemplar info
        tgt_dj = json.loads(
            self.con.execute("SELECT data_json FROM nodes WHERE id = 2").fetchone()[0]
        )
        self.assertEqual(tgt_dj["exemplar_ids"], ["11", "10"])
        self.assertEqual(tgt_dj["supporting_quotes"]["10"], "quote A")
        self.assertEqual(tgt_dj["supporting_quotes"]["11"], "quote B")

        # Contains edges: source's migrated to target
        src_contains = self.con.execute(
            "SELECT target_id FROM edges "
            "WHERE source_id = 1 AND edge_type = 'contains'"
        ).fetchall()
        self.assertEqual(len(src_contains), 0)

        tgt_contains = self.con.execute(
            "SELECT target_id FROM edges "
            "WHERE source_id = 2 AND edge_type = 'contains' "
            "ORDER BY target_id"
        ).fetchall()
        self.assertEqual(len(tgt_contains), 2)
        self.assertEqual(tgt_contains[0][0], 10)
        self.assertEqual(tgt_contains[1][0], 11)

        # derived-from edge exists
        df_edge = self.con.execute(
            "SELECT 1 FROM edges "
            "WHERE source_id = 1 AND target_id = 2 AND edge_type = 'derived-from'"
        ).fetchone()
        self.assertIsNotNone(df_edge)

    def test_merge_handles_existing_target_connection(self):
        """When target already contains the same exemplar, redirect succeeds."""
        self._create_code_node(
            1,
            name="CodeA",
            exemplar_ids=["10"],
            supporting_quotes={"10": "quote A"},
        )
        self._create_code_node(
            2,
            name="CodeB",
            exemplar_ids=["10"],
            supporting_quotes={"10": "quote B"},
        )
        self._create_exemplar_node(10, "10")
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) "
            "VALUES (1, 10, 'contains')"
        )
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) "
            "VALUES (2, 10, 'contains')"
        )

        source_code = self._code_dict(1)
        handle_merge(self.con, source_code, target_id=2, db_path=self.db_path)

        # Source has no contains edges left
        src_contains = self.con.execute(
            "SELECT target_id FROM edges "
            "WHERE source_id = 1 AND edge_type = 'contains'"
        ).fetchall()
        self.assertEqual(len(src_contains), 0)

        # Target still has its contains edge
        tgt_contains = self.con.execute(
            "SELECT target_id FROM edges "
            "WHERE source_id = 2 AND edge_type = 'contains'"
        ).fetchall()
        self.assertEqual(len(tgt_contains), 1)
        self.assertEqual(tgt_contains[0][0], 10)

    def test_merge_skips_self_merge(self):
        self._create_code_node(1)
        source_code = self._code_dict(1)
        handle_merge(self.con, source_code, target_id=1, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "draft")

    # ── Reject ───────────────────────────────────────────────────────────

    def test_reject_updates_status_and_inference(self):
        self._create_code_node(1)
        code = self._code_dict(1)
        handle_reject(self.con, code, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "rejected")

        inf_status = self.con.execute(
            "SELECT status FROM inference_status "
            "WHERE entity_id = '1' AND entity_type = 'code' AND stage = 'code'"
        ).fetchone()[0]
        self.assertEqual(inf_status, "rejected")

    # ── Defer ────────────────────────────────────────────────────────────

    def test_defer_does_not_change_status(self):
        self._create_code_node(1)
        code = self._code_dict(1)
        handle_defer(self.con, code, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "draft")


if __name__ == "__main__":
    unittest.main()
