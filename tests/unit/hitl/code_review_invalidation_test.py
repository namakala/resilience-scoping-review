"""Tests for Feature 41 code-edit-embeddings-invalidation acceptance criteria.

Verifies:
- Edit sets dirty flag for the code's tag branch (AC #3)
- Merge deletes embedding cache rows for source and target codes
- Merge sets dirty flag for the tag branch
- ``invalidate_code_embedding`` works as centralized function
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
import numpy as np
from hitl.code_review_actions import handle_edit
from hitl.code_review_merge import handle_merge
from hitl.edits import invalidate_code_embedding
from inference.inference_status_crud import init_inference_status_table
from persistence.duckdb_init import initialize_database
from persistence.state_updates import get_dirty_flags


class TestEditInvalidation(unittest.TestCase):
    """AC: Edit via HITL CLI sets dirty flag; embedding cache entry removed."""

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
        definition="original def",
        tag="T1",
        status="draft",
    ):
        dj = json.dumps({"exemplar_ids": [str(node_id)]})
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

    def _seed_embedding_cache(self, entity_id, entity_type="code"):
        self.con.execute(
            "INSERT INTO embedding_cache "
            "(entity_id, entity_type, embedding, model_hash, content_hash) "
            "VALUES (?, ?, ?::BLOB, 'mh', 'ch')",
            [
                entity_id,
                entity_type,
                np.array([0.1, 0.2, 0.3], dtype="float32").tobytes(),
            ],
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

    # ── Tests ────────────────────────────────────────────────────────────

    def test_edit_sets_dirty_flag(self):
        """AC #3: Editing a code sets its tag's dirty flag to True."""
        self._create_code_node(1, tag="Problem.Cause")
        self._seed_embedding_cache("1")
        code = self._code_dict(1)

        handle_edit(self.con, code, db_path=self.db_path, new_definition="updated def")

        flags = get_dirty_flags(self.con)
        self.assertIn("Problem.Cause", flags)
        self.assertTrue(flags["Problem.Cause"])

    def test_edit_removes_embedding_cache(self):
        """AC #2: Editing a code removes its embedding cache entry."""
        self._create_code_node(1, tag="T1")
        self._seed_embedding_cache("1")
        code = self._code_dict(1)

        handle_edit(self.con, code, db_path=self.db_path, new_definition="updated def")

        cached = self.con.execute(
            "SELECT 1 FROM embedding_cache "
            "WHERE entity_id = '1' AND entity_type = 'code'"
        ).fetchone()
        self.assertIsNone(cached)

    def test_edit_sets_dirty_flag_only_with_tag(self):
        """Editing a code with empty tag does not raise."""
        self._create_code_node(1, tag="")
        self._seed_embedding_cache("1")
        code = self._code_dict(1)

        # Should not raise even with empty tag
        handle_edit(self.con, code, db_path=self.db_path, new_definition="updated def")

        flags = get_dirty_flags(self.con)
        self.assertEqual(flags, {})


class TestMergeInvalidation(unittest.TestCase):
    """AC: Merge invalidates code embeddings and sets dirty flag."""

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

    def _seed_embedding_cache(self, entity_id, entity_type="code"):
        self.con.execute(
            "INSERT INTO embedding_cache "
            "(entity_id, entity_type, embedding, model_hash, content_hash) "
            "VALUES (?, ?, ?::BLOB, 'mh', 'ch')",
            [
                entity_id,
                entity_type,
                np.array([0.1, 0.2, 0.3], dtype="float32").tobytes(),
            ],
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
    def test_merge_removes_source_embedding_cache(self, mock_validate):
        """Merge deletes embedding cache for the source code."""
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
        self._seed_embedding_cache("1")
        self._seed_embedding_cache("2")

        source_code = self._code_dict(1)
        handle_merge(self.con, source_code, target_id=2, db_path=self.db_path)

        src_cached = self.con.execute(
            "SELECT 1 FROM embedding_cache "
            "WHERE entity_id = '1' AND entity_type = 'code'"
        ).fetchone()
        self.assertIsNone(src_cached)

    @patch("hitl.code_review_merge.validate_constraint")
    def test_merge_removes_target_embedding_cache(self, mock_validate):
        """Merge deletes embedding cache for the target code."""
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
        self._seed_embedding_cache("1")
        self._seed_embedding_cache("2")

        source_code = self._code_dict(1)
        handle_merge(self.con, source_code, target_id=2, db_path=self.db_path)

        tgt_cached = self.con.execute(
            "SELECT 1 FROM embedding_cache "
            "WHERE entity_id = '2' AND entity_type = 'code'"
        ).fetchone()
        self.assertIsNone(tgt_cached)

    @patch("hitl.code_review_merge.validate_constraint")
    def test_merge_sets_dirty_flag(self, mock_validate):
        """Merge sets dirty flag for the code's tag branch."""
        self._create_code_node(
            1, name="CodeA", tag="Problem.Cause", exemplar_ids=["10"]
        )
        self._create_code_node(
            2, name="CodeB", tag="Problem.Cause", exemplar_ids=["11"]
        )
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

        flags = get_dirty_flags(self.con)
        self.assertIn("Problem.Cause", flags)
        self.assertTrue(flags["Problem.Cause"])


class TestInvalidateCodeEmbeddingDirect(unittest.TestCase):
    """Direct tests for the centralized ``invalidate_code_embedding`` function."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))
        import graph.singleton as singleton

        singleton._graph = None

    def tearDown(self):
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.singleton as singleton

        singleton._graph = None

    def _seed_embedding_cache(self, entity_id, entity_type="code"):
        self.con.execute(
            "INSERT INTO embedding_cache "
            "(entity_id, entity_type, embedding, model_hash, content_hash) "
            "VALUES (?, ?, ?::BLOB, 'mh', 'ch')",
            [
                entity_id,
                entity_type,
                np.array([0.1, 0.2, 0.3], dtype="float32").tobytes(),
            ],
        )

    def test_invalidate_removes_cache_entry(self):
        """Calling invalidate_code_embedding removes the cache entry."""
        self._seed_embedding_cache("42")
        invalidate_code_embedding(self.con, 42, "T1")

        cached = self.con.execute(
            "SELECT 1 FROM embedding_cache "
            "WHERE entity_id = '42' AND entity_type = 'code'"
        ).fetchone()
        self.assertIsNone(cached)

    def test_invalidate_sets_dirty_flag(self):
        """Calling invalidate_code_embedding sets the dirty flag."""
        invalidate_code_embedding(self.con, 42, "Problem.Cause")

        flags = get_dirty_flags(self.con)
        self.assertIn("Problem.Cause", flags)
        self.assertTrue(flags["Problem.Cause"])

    def test_invalidate_with_empty_tag_skips_dirty_flag(self):
        """Calling with empty tag deletes cache but does not set dirty flag."""
        self._seed_embedding_cache("99")
        invalidate_code_embedding(self.con, 99, "")

        cached = self.con.execute(
            "SELECT 1 FROM embedding_cache "
            "WHERE entity_id = '99' AND entity_type = 'code'"
        ).fetchone()
        self.assertIsNone(cached)

        flags = get_dirty_flags(self.con)
        self.assertEqual(flags, {})

    def test_invalidate_nonexistent_cache_does_not_raise(self):
        """Calling invalidate on a code without cached embedding does not raise."""
        # No cache entry seeded — should not raise
        invalidate_code_embedding(self.con, 999, "T1")


if __name__ == "__main__":
    unittest.main()
