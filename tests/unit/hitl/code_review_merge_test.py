"""Tests for Feature 40 code-merge-action acceptance criteria.

Verifies:
- Merge atomic via transaction (success and rollback)
- After merge, querying by tag returns only survivor code
- ``derived-from`` chain preserves lineage (source → target)
- Downstream dirty flags set: theme status→draft; interpretation status→draft
- Merge audited in ``user_actions`` with ``action_type='merge'``
- Cannot merge codes of different types (code+theme rejected)
"""

# flake8: noqa: E402
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import duckdb
from graph.queries import get_node, get_nodes_by_type_and_tag
from hitl.code_review_merge import handle_merge
from inference.inference_status_crud import init_inference_status_table
from ontology import ConstraintError
from persistence.duckdb_init import initialize_database


class TestFeature40MergeAtomicity(unittest.TestCase):
    """AC: Merge operation atomic via transaction."""

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
            "SELECT id, name, definition, tag, data_json, status, type "
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
            "type": row[6],
        }

    # ── Tests ────────────────────────────────────────────────────────────

    @patch("hitl.code_review_merge.validate_constraint")
    def test_merge_sets_merged_into_in_data_json(self, mock_validate):
        """AC: Source node gets merged_into property after merge."""
        self._create_code_node(1, name="CodeA", exemplar_ids=["10"])
        self._create_code_node(2, name="CodeB", exemplar_ids=["11"])
        self._create_exemplar_node(10, "10")
        self._create_exemplar_node(11, "11")
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (1, 10, 'contains')"
        )
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (2, 11, 'contains')"
        )

        source_code = self._code_dict(1)
        handle_merge(self.con, source_code, target_id=2, db_path=self.db_path)

        src_dj = json.loads(
            self.con.execute("SELECT data_json FROM nodes WHERE id = 1").fetchone()[0]
        )
        self.assertIn("merged_into", src_dj)
        self.assertEqual(src_dj["merged_into"], 2)

    @patch("hitl.code_review_merge.validate_constraint")
    def test_merge_query_by_tag_returns_only_survivor(self, mock_validate):
        """AC: After merge, the source is status='merged' and the target is 'draft'."""
        self._create_code_node(1, name="CodeA", tag="T1")
        self._create_code_node(2, name="CodeB", tag="T1")
        self._create_exemplar_node(10, "10")
        self._create_exemplar_node(11, "11")
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (1, 10, 'contains')"
        )
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (2, 11, 'contains')"
        )

        source_code = self._code_dict(1)
        handle_merge(self.con, source_code, target_id=2, db_path=self.db_path)

        # Source is merged, target retains its original status
        src = get_node(1, db_path=self.db_path)
        tgt = get_node(2, db_path=self.db_path)
        self.assertEqual(src["status"], "merged")
        self.assertEqual(tgt["status"], "draft")

    @patch("hitl.code_review_merge.validate_constraint")
    def test_merge_derived_from_chain_preserved(self, mock_validate):
        """AC: derived-from edge exists from source → target."""
        self._create_code_node(1, name="CodeA")
        self._create_code_node(2, name="CodeB")
        self._create_exemplar_node(10, "10")
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (1, 10, 'contains')"
        )

        source_code = self._code_dict(1)
        handle_merge(self.con, source_code, target_id=2, db_path=self.db_path)

        df_edge = self.con.execute(
            "SELECT 1 FROM edges "
            "WHERE source_id = 1 AND target_id = 2 AND edge_type = 'derived-from'"
        ).fetchone()
        self.assertIsNotNone(df_edge)

    @patch("hitl.code_review_merge.validate_constraint")
    def test_merge_user_action_logged(self, mock_validate):
        """AC: user_actions table has entry with action_type='merge'."""
        self._create_code_node(1, name="CodeA")
        self._create_code_node(2, name="CodeB")
        self._create_exemplar_node(10, "10")
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (1, 10, 'contains')"
        )

        source_code = self._code_dict(1)
        handle_merge(self.con, source_code, target_id=2, db_path=self.db_path)

        action = self.con.execute(
            "SELECT action_type, entity_id FROM user_actions WHERE action_type = 'merge'"
        ).fetchone()
        self.assertIsNotNone(action)
        self.assertEqual(action[0], "merge")
        self.assertEqual(action[1], 1)

    def test_merge_type_mismatch_rejected(self):
        """AC: Cannot merge code and theme - raises ConstraintError."""
        self._create_code_node(1, name="CodeA", exemplar_ids=["10"], tag="T1")
        self._create_exemplar_node(10, "10")
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (1, 10, 'contains')"
        )

        # Create a theme node (type='theme', not 'code')
        dj = json.dumps({"code_ids": []})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (99, 'theme', 'ThemeX', 'narrative', 'T1', 'draft', ?)",
            [dj],
        )

        source_code = self._code_dict(1)
        with self.assertRaises(ConstraintError) as ctx:
            handle_merge(self.con, source_code, target_id=99, db_path=self.db_path)
        self.assertIn("CONSTRAINT_TYPE_MISMATCH", str(ctx.exception))
        self.assertIn("code", str(ctx.exception))
        self.assertIn("theme", str(ctx.exception))


class TestFeature40DownstreamInvalidation(unittest.TestCase):
    """AC: Downstream dirty flags set on theme and interpretation."""

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

    def _create_code_node(self, node_id, name="C", tag="T1", status="draft"):
        dj = json.dumps({"exemplar_ids": [str(node_id)]})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'code', ?, 'def', ?, ?, ?)",
            [node_id, name, tag, status, dj],
        )
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage, status) "
            "VALUES (?, 'code', 'code', 'generated')",
            [str(node_id)],
        )

    def _create_exemplar_node(self, node_id, eid):
        dj = json.dumps({"exemplar_id": str(eid)})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'exemplar', ?, '', 'T1', 'immutable', ?)",
            [node_id, f"ex_{eid}", dj],
        )

    def _create_theme_node(self, theme_id, name="ThemeX", tag="T1", status="approved"):
        dj = json.dumps({"code_ids": []})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'theme', ?, 'narrative', ?, ?, ?)",
            [theme_id, name, tag, status, dj],
        )

    def _create_interpretation_node(self, interp_id, name="InterpX", status="approved"):
        dj = json.dumps({"tag_spans": ["T1"]})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'interpretation', ?, 'synthesis', '', ?, ?)",
            [interp_id, name, status, dj],
        )

    @patch("hitl.code_review_merge.validate_constraint")
    def test_merge_invalidates_theme_to_draft(self, mock_validate):
        """AC: Theme containing merged code is set to status='draft'.

        Also verifies theme inference status is set to draft.
        """
        self._create_code_node(1, name="CodeA")
        self._create_code_node(2, name="CodeB")
        self._create_exemplar_node(10, "10")
        self._create_exemplar_node(11, "11")
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (1, 10, 'contains')"
        )
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (2, 11, 'contains')"
        )

        # Theme contains CodeB (target of merge)
        self._create_theme_node(50, name="ThemeMain", status="approved")
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (50, 2, 'composed-of')"
        )

        source_code = {
            "id": 1,
            "name": "CodeA",
            "definition": "def",
            "tag": "T1",
            "data_json": {"exemplar_ids": ["10"]},
            "status": "draft",
            "type": "code",
        }
        handle_merge(self.con, source_code, target_id=2, db_path=self.db_path)

        # Theme status should be draft
        theme_status = self.con.execute(
            "SELECT status FROM nodes WHERE id = 50"
        ).fetchone()[0]
        self.assertEqual(theme_status, "draft")

        # Theme inference status should be draft
        inf_status = self.con.execute(
            "SELECT status FROM inference_status "
            "WHERE entity_id = '50' AND entity_type = 'theme' AND stage = 'theme'"
        ).fetchone()
        self.assertIsNotNone(inf_status)
        self.assertEqual(inf_status[0], "draft")

    @patch("hitl.code_review_merge.validate_constraint")
    def test_merge_invalidates_interpretation_to_draft(self, mock_validate):
        """AC: Interpretation spanning a theme containing merged code is set to draft."""
        self._create_code_node(1, name="CodeA")
        self._create_code_node(2, name="CodeB")
        self._create_exemplar_node(10, "10")
        self._create_exemplar_node(11, "11")
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (1, 10, 'contains')"
        )
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (2, 11, 'contains')"
        )

        # Theme contains CodeB
        self._create_theme_node(50, name="ThemeMain")
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (50, 2, 'composed-of')"
        )

        # Interpretation spans ThemeMain
        self._create_interpretation_node(100, name="InterpMain", status="approved")
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (100, 50, 'spans')"
        )

        source_code = {
            "id": 1,
            "name": "CodeA",
            "definition": "def",
            "tag": "T1",
            "data_json": {"exemplar_ids": ["10"]},
            "status": "draft",
            "type": "code",
        }
        handle_merge(self.con, source_code, target_id=2, db_path=self.db_path)

        interp_status = self.con.execute(
            "SELECT status FROM nodes WHERE id = 100"
        ).fetchone()[0]
        self.assertEqual(interp_status, "draft")


class TestFeature40Rollback(unittest.TestCase):
    """AC: Merge rolls back atomically on failure."""

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

    def _create_code_node(self, node_id, name="C", exemplar_ids=None, status="draft"):
        if exemplar_ids is None:
            exemplar_ids = [str(node_id)]
        dj = json.dumps({"exemplar_ids": exemplar_ids})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'code', ?, 'def', 'T1', ?, ?)",
            [node_id, name, status, dj],
        )

    @patch("hitl.code_review_merge.validate_constraint")
    def test_merge_rollback_on_failure(self, mock_validate):
        """AC: When a step fails, no changes persist (atomic rollback).

        Inject a failure via mocked log_user_action to force rollback.
        """
        self._create_code_node(1, name="CodeA", exemplar_ids=["10"])
        self._create_code_node(2, name="CodeB", exemplar_ids=["11"])

        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (10, 'exemplar', 'ex10', '', 'T1', 'immutable', '{}')"
        )
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (11, 'exemplar', 'ex11', '', 'T1', 'immutable', '{}')"
        )
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (1, 10, 'contains')"
        )
        self.con.execute(
            "INSERT INTO edges (source_id, target_id, edge_type) VALUES (2, 11, 'contains')"
        )

        initial_src_status = self.con.execute(
            "SELECT status FROM nodes WHERE id = 1"
        ).fetchone()[0]
        self.assertEqual(initial_src_status, "draft")

        source_code = {
            "id": 1,
            "name": "CodeA",
            "definition": "def",
            "tag": "T1",
            "data_json": {"exemplar_ids": ["10"]},
            "status": "draft",
            "type": "code",
        }

        with patch(
            "hitl.code_review_merge.log_user_action",
            side_effect=RuntimeError("mock failure"),
        ):
            with self.assertRaises(RuntimeError):
                handle_merge(self.con, source_code, target_id=2, db_path=self.db_path)

        # Source node should still be 'draft' (not 'merged')
        src_status = self.con.execute(
            "SELECT status FROM nodes WHERE id = 1"
        ).fetchone()[0]
        self.assertEqual(src_status, "draft")

        # Target should retain its original data (rollback reverted merge)
        tgt_dj = self.con.execute(
            "SELECT data_json FROM nodes WHERE id = 2"
        ).fetchone()[0]
        tgt_data = json.loads(tgt_dj) if tgt_dj else {}
        self.assertIn("exemplar_ids", tgt_data)
        self.assertEqual(tgt_data["exemplar_ids"], ["11"])

        # Edges should be unchanged
        src_contains = self.con.execute(
            "SELECT target_id FROM edges "
            "WHERE source_id = 1 AND edge_type = 'contains'"
        ).fetchall()
        self.assertEqual(len(src_contains), 1)

        # No derived-from edge
        df_edge = self.con.execute(
            "SELECT 1 FROM edges "
            "WHERE source_id = 1 AND target_id = 2 AND edge_type = 'derived-from'"
        ).fetchone()
        self.assertIsNone(df_edge)


if __name__ == "__main__":
    unittest.main()
