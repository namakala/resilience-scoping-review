"""Tests for code review CLI orchestration with mocked prompts.

Tests review_codes() entry point with mocked questionary prompts and
neighbor discovery.
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

import duckdb
from inference.inference_status_crud import init_inference_status_table
from persistence.duckdb_init import initialize_database


class TestCodeReviewOrchestration(unittest.TestCase):
    """Tests for review_codes() entry point with mocked interactive prompts."""

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

    def _insert_draft_code(self, node_id, name="TestCode", definition="def", tag="T1"):
        dj = json.dumps(
            {
                "exemplar_ids": [str(node_id)],
                "supporting_quotes": {str(node_id): "quote"},
                "related_existing_codes": [],
            }
        )
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'code', ?, ?, ?, 'draft', ?)",
            [node_id, name, definition, tag, dj],
        )

    # ── No pending codes ─────────────────────────────────────────────────

    def test_no_pending_codes_returns_early(self):
        from hitl.code_review import review_codes

        with mock.patch("hitl.shared.console.print") as mock_print:
            review_codes(self.con, db_path=self.db_path)
            mock_print.assert_called_once()
            msg = str(mock_print.call_args[0][0])
            self.assertIn("No pending codes", msg)

    # ── Keyboard interrupt ───────────────────────────────────────────────

    def test_keyboard_interrupt_graceful(self):
        from hitl.code_review import review_codes

        self._insert_draft_code(1)
        with mock.patch(
            "hitl.code_review._review_single_code",
            side_effect=KeyboardInterrupt(),
        ):
            with mock.patch("hitl.shared.console.print") as mock_print:
                review_codes(self.con, db_path=self.db_path)
                printed = [str(c[0][0]) for c in mock_print.call_args_list]
                self.assertTrue(any("interrupted" in p.lower() for p in printed))

    # ── Approve via prompt ───────────────────────────────────────────────

    @mock.patch("questionary.select")
    @mock.patch("ontology.validate_constraint")
    def test_approve_via_prompt(self, mock_validate, mock_select):
        from hitl.code_review import review_codes

        mock_validate.return_value = None
        self._insert_draft_code(1, name="CodeA")
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage, status) "
            "VALUES ('1', 'code', 'code', 'generated')"
        )
        mock_select.return_value.ask.return_value = "Approve"

        with (
            mock.patch("hitl.shared.console.print"),
            mock.patch("hitl.code_review._get_neighbors", return_value=[]),
        ):
            review_codes(self.con, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "approved")

    # ── Reject via prompt ────────────────────────────────────────────────

    @mock.patch("questionary.select")
    def test_reject_via_prompt(self, mock_select):
        from hitl.code_review import review_codes

        self._insert_draft_code(1, name="CodeA")
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage, status) "
            "VALUES ('1', 'code', 'code', 'generated')"
        )
        mock_select.return_value.ask.return_value = "Reject"

        with (
            mock.patch("hitl.shared.console.print"),
            mock.patch("hitl.code_review._get_neighbors", return_value=[]),
        ):
            review_codes(self.con, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "rejected")

    # ── Defer via prompt ─────────────────────────────────────────────────

    @mock.patch("questionary.select")
    def test_defer_via_prompt(self, mock_select):
        from hitl.code_review import review_codes

        self._insert_draft_code(1, name="CodeA")
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage, status) "
            "VALUES ('1', 'code', 'code', 'generated')"
        )
        mock_select.return_value.ask.return_value = "Defer"

        with (
            mock.patch("hitl.shared.console.print"),
            mock.patch("hitl.code_review._get_neighbors", return_value=[]),
        ):
            review_codes(self.con, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "draft")


if __name__ == "__main__":
    unittest.main()
