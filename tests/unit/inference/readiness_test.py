"""Unit tests for interpretation readiness tracking (Feature 46).

Tests ``check_tag_ready``, ``remove_tag_from_ready``, ``get_ready_tags``,
and ``is_tag_in_ready_list`` against an in-memory DuckDB with mocked
ontology traversal.
"""

# flake8: noqa: E402
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

from typing import Any, cast

import duckdb
from persistence.duckdb_init import initialize_database


class TestReadiness(unittest.TestCase):
    """Test suite for interpretation readiness tracking."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))
        # Ensure session_state table exists with default workflow row
        self.con.execute(
            "INSERT OR REPLACE INTO session_state (key, value, type) "
            "VALUES ('workflow', '{}', 'dict')"
        )

    def tearDown(self):
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)

    # ── Helpers ─────────────────────────────────────────────────────────

    def _insert_theme(self, theme_id, tag, status="draft"):
        """Insert a theme node with given status."""
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'theme', ?, ?, ?, ?, '{}')",
            [theme_id, f"Theme{theme_id}", f"narrative for {theme_id}", tag, status],
        )

    def _get_state_value(self) -> str:
        """Return raw JSON string from session_state workflow row."""
        row = self.con.execute(
            "SELECT value FROM session_state WHERE key = 'workflow'"
        ).fetchone()
        return cast(str, row[0]) if row else "{}"

    def _get_ready_tags(self) -> list:
        """Parse ready tags from stored state."""
        raw = json.loads(self._get_state_value())
        return cast(list, raw.get("interpretation_ready_tags", []))

    # ── Subtree fully approved ──────────────────────────────────────────

    @mock.patch("inference.readiness.get_subtree")
    @mock.patch("inference.readiness.get_ancestors")
    def test_subtree_fully_approved(self, mock_ancestors, mock_subtree):
        """All themes across subtree approved → tag is ready.

        Tag A has 2 approved themes. Child A.B has 1 approved theme.
        """
        mock_subtree.return_value = {"A", "A.B"}
        mock_ancestors.return_value = []
        self._insert_theme(1, "A", "approved")
        self._insert_theme(2, "A", "approved")
        self._insert_theme(3, "A.B", "approved")

        from inference.readiness import check_tag_ready

        result = check_tag_ready(self.con, "A")
        self.assertTrue(result)
        self.assertIn("A", self._get_ready_tags())

    # ── Draft theme blocks readiness ─────────────────────────────────────

    @mock.patch("inference.readiness.get_subtree")
    @mock.patch("inference.readiness.get_ancestors")
    def test_subtree_has_draft_blocks_ready(self, mock_ancestors, mock_subtree):
        """A draft theme anywhere in subtree → not ready."""
        mock_subtree.return_value = {"A", "A.B"}
        mock_ancestors.return_value = []
        self._insert_theme(1, "A", "approved")
        self._insert_theme(2, "A.B", "draft")

        from inference.readiness import check_tag_ready

        result = check_tag_ready(self.con, "A")
        self.assertFalse(result)
        self.assertEqual(self._get_ready_tags(), [])

    # ── Rejected theme blocks readiness ──────────────────────────────────

    @mock.patch("inference.readiness.get_subtree")
    @mock.patch("inference.readiness.get_ancestors")
    def test_subtree_has_rejected_blocks_ready(self, mock_ancestors, mock_subtree):
        """A rejected theme anywhere in subtree → not ready."""
        mock_subtree.return_value = {"A", "A.B"}
        mock_ancestors.return_value = []
        self._insert_theme(1, "A", "approved")
        self._insert_theme(2, "A.B", "rejected")

        from inference.readiness import check_tag_ready

        result = check_tag_ready(self.con, "A")
        self.assertFalse(result)
        self.assertEqual(self._get_ready_tags(), [])

    # ── Ancestors included in ready list ─────────────────────────────────

    @mock.patch("inference.readiness.get_subtree")
    @mock.patch("inference.readiness.get_ancestors")
    def test_ancestors_added_to_ready_list(self, mock_ancestors, mock_subtree):
        """When A.B is ready, list contains A.B and ancestor A."""
        mock_subtree.return_value = {"A.B"}
        mock_ancestors.return_value = ["A"]
        self._insert_theme(1, "A.B", "approved")

        from inference.readiness import check_tag_ready

        result = check_tag_ready(self.con, "A.B")
        self.assertTrue(result)
        ready = self._get_ready_tags()
        self.assertIn("A.B", ready)
        self.assertIn("A", ready)

    # ── Remove tag and ancestors ─────────────────────────────────────────

    @mock.patch("inference.readiness.get_subtree")
    @mock.patch("inference.readiness.get_ancestors")
    def test_remove_tag_and_ancestors(self, mock_ancestors, mock_subtree):
        """After removal, neither tag nor ancestors remain in list."""
        # First mark ready
        mock_subtree.return_value = {"A.B"}
        mock_ancestors.return_value = ["A"]
        self._insert_theme(1, "A.B", "approved")

        from inference.readiness import check_tag_ready, remove_tag_from_ready

        check_tag_ready(self.con, "A.B")
        self.assertIn("A.B", self._get_ready_tags())
        self.assertIn("A", self._get_ready_tags())

        # Now remove
        remove_tag_from_ready(self.con, "A.B")
        ready = self._get_ready_tags()
        self.assertNotIn("A.B", ready)
        self.assertNotIn("A", ready)

    # ── Remove idempotent ────────────────────────────────────────────────

    @mock.patch("inference.readiness.get_ancestors")
    def test_remove_tag_not_in_list(self, mock_ancestors):
        """Removing a tag not in the ready list is a no-op."""
        mock_ancestors.return_value = []

        from inference.readiness import remove_tag_from_ready

        # Should not raise
        remove_tag_from_ready(self.con, "NonExistent")
        self.assertEqual(self._get_ready_tags(), [])

    # ── Empty subtag does not block ──────────────────────────────────────

    @mock.patch("inference.readiness.get_subtree")
    @mock.patch("inference.readiness.get_ancestors")
    def test_empty_subtag_does_not_block(self, mock_ancestors, mock_subtree):
        """Tag A has approved theme; child A.B has 0 themes → still ready."""
        mock_subtree.return_value = {"A", "A.B"}
        mock_ancestors.return_value = []
        self._insert_theme(1, "A", "approved")

        from inference.readiness import check_tag_ready

        result = check_tag_ready(self.con, "A")
        self.assertTrue(result)
        self.assertIn("A", self._get_ready_tags())

    # ── Dirty flag set ───────────────────────────────────────────────────

    @mock.patch("inference.readiness.get_subtree")
    @mock.patch("inference.readiness.get_ancestors")
    def test_dirty_flag_set_when_ready(self, mock_ancestors, mock_subtree):
        """When tag becomes ready, dirty_flags[tag] is set to True."""
        mock_subtree.return_value = {"A"}
        mock_ancestors.return_value = []
        self._insert_theme(1, "A", "approved")

        # Ensure session_state has the workflow row with empty dirty_flags
        state = json.loads(self._get_state_value())
        state["dirty_flags"] = {}
        self.con.execute(
            "INSERT OR REPLACE INTO session_state (key, value, type) "
            "VALUES ('workflow', ?, 'dict')",
            [json.dumps(state)],
        )

        from inference.readiness import check_tag_ready

        check_tag_ready(self.con, "A")

        state = json.loads(self._get_state_value())
        self.assertTrue(state.get("dirty_flags", {}).get("A"))

    # ── Get ready tags returns current list ──────────────────────────────

    def test_get_ready_tags(self):
        """get_ready_tags returns current list from session state."""
        state = json.loads(self._get_state_value())
        state["interpretation_ready_tags"] = ["A", "B"]
        self.con.execute(
            "INSERT OR REPLACE INTO session_state (key, value, type) "
            "VALUES ('workflow', ?, 'dict')",
            [json.dumps(state)],
        )

        from inference.readiness import get_ready_tags

        ready = get_ready_tags(self.con)
        self.assertEqual(ready, ["A", "B"])

    # ── Is tag in ready list ─────────────────────────────────────────────

    def test_is_tag_in_ready_list(self):
        """is_tag_in_ready_list correctly reports membership."""
        state = json.loads(self._get_state_value())
        state["interpretation_ready_tags"] = ["A"]
        self.con.execute(
            "INSERT OR REPLACE INTO session_state (key, value, type) "
            "VALUES ('workflow', ?, 'dict')",
            [json.dumps(state)],
        )

        from inference.readiness import is_tag_in_ready_list

        self.assertTrue(is_tag_in_ready_list(self.con, "A"))
        self.assertFalse(is_tag_in_ready_list(self.con, "B"))


if __name__ == "__main__":
    unittest.main()
