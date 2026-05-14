"""Tests for theme review CLI orchestration with mocked prompts.

Tests review_themes() entry point with mocked questionary prompts and
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


class TestThemeReviewOrchestration(unittest.TestCase):
    """Tests for review_themes() entry point with mocked interactive prompts."""

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

    # ── Helpers ─────────────────────────────────────────────────────────

    def _insert_draft_theme(
        self,
        theme_id,
        name="ThemeA",
        narrative="test narrative",
        tag="T1",
        code_ids=None,
    ):
        code_ids = code_ids or []
        dj = json.dumps({"code_ids": code_ids})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'theme', ?, ?, ?, 'draft', ?)",
            [theme_id, name, narrative, tag, dj],
        )
        for cid in code_ids:
            self.con.execute(
                "INSERT INTO edges (source_id, target_id, edge_type) "
                "VALUES (?, ?, 'composed-of')",
                [theme_id, cid],
            )

    def _insert_mock_code(self, code_id, name="CodeA", tag="T1", exemplar_count=2):
        eids = [str(i) for i in range(exemplar_count)]
        dj = json.dumps({"exemplar_ids": eids, "supporting_quotes": {}})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'code', ?, ?, ?, 'approved', ?)",
            [code_id, name, f"Definition for {name}", tag, dj],
        )

    # ── No pending themes ───────────────────────────────────────────────

    def test_no_pending_themes_returns_early(self):
        from hitl.theme_review import review_themes

        with mock.patch("hitl.shared.console.print") as mock_print:
            review_themes(self.con, db_path=self.db_path)
            mock_print.assert_called_once()
            msg = str(mock_print.call_args[0][0])
            self.assertIn("No pending themes", msg)

    # ── Keyboard interrupt ──────────────────────────────────────────────

    def test_keyboard_interrupt_graceful(self):
        from hitl.theme_review import review_themes

        self._insert_draft_theme(1)
        with mock.patch(
            "hitl.theme_review._review_single_theme",
            side_effect=KeyboardInterrupt(),
        ):
            with mock.patch("hitl.shared.console.print") as mock_print:
                review_themes(self.con, db_path=self.db_path)
                printed = [str(c[0][0]) for c in mock_print.call_args_list]
                self.assertTrue(any("interrupted" in p.lower() for p in printed))

    # ── Approve via prompt ──────────────────────────────────────────────

    @mock.patch("inference.readiness.check_tag_ready")
    @mock.patch("questionary.select")
    @mock.patch("ontology.validate_constraint")
    def test_approve_via_prompt(self, mock_constraint, mock_select, mock_readiness):
        from hitl.theme_review import review_themes

        self._insert_draft_theme(1, name="ThemeA", code_ids=[10, 11])
        self._insert_mock_code(10, "CodeA", "T1")
        self._insert_mock_code(11, "CodeB", "T1")
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage, status) "
            "VALUES ('1', 'theme', 'theme', 'generated')"
        )
        mock_select.return_value.ask.return_value = "Approve"
        mock_constraint.return_value = None
        mock_readiness.return_value = False

        with (
            mock.patch("hitl.shared.console.print"),
            mock.patch("hitl.theme_review.get_theme_neighbors", return_value=[]),
            mock.patch("hitl.theme_review.get_constituent_codes", return_value=[]),
        ):
            review_themes(self.con, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "approved")
        mock_readiness.assert_called_once_with(mock.ANY, "T1", db_path=mock.ANY)

    # ── Reject via prompt ───────────────────────────────────────────────

    @mock.patch("inference.readiness.check_tag_ready")
    @mock.patch("questionary.select")
    def test_reject_via_prompt(self, mock_select, mock_readiness):
        from hitl.theme_review import review_themes

        self._insert_draft_theme(1, name="ThemeA", code_ids=[10, 11])
        self._insert_mock_code(10, "CodeA", "T1")
        self._insert_mock_code(11, "CodeB", "T1")
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage, status) "
            "VALUES ('1', 'theme', 'theme', 'generated')"
        )
        mock_select.return_value.ask.return_value = "Reject"

        with (
            mock.patch("hitl.shared.console.print"),
            mock.patch("hitl.theme_review.get_theme_neighbors", return_value=[]),
            mock.patch("hitl.theme_review.get_constituent_codes", return_value=[]),
        ):
            review_themes(self.con, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "rejected")
        mock_readiness.assert_called_once_with(mock.ANY, "T1", db_path=mock.ANY)

    # ── Defer via prompt ────────────────────────────────────────────────

    @mock.patch("questionary.select")
    def test_defer_via_prompt(self, mock_select):
        from hitl.theme_review import review_themes

        self._insert_draft_theme(1, name="ThemeA", code_ids=[10, 11])
        self._insert_mock_code(10, "CodeA", "T1")
        self._insert_mock_code(11, "CodeB", "T1")
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage, status) "
            "VALUES ('1', 'theme', 'theme', 'generated')"
        )
        mock_select.return_value.ask.return_value = "Defer"

        with (
            mock.patch("hitl.shared.console.print"),
            mock.patch("hitl.theme_review.get_theme_neighbors", return_value=[]),
            mock.patch("hitl.theme_review.get_constituent_codes", return_value=[]),
        ):
            review_themes(self.con, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "draft")

    # ── Edit narrative via prompt ───────────────────────────────────────

    @mock.patch("inference.readiness.check_tag_ready")
    @mock.patch("questionary.select")
    @mock.patch("questionary.text")
    @mock.patch("questionary.checkbox")
    @mock.patch("hitl.prompts_themes.get_available_codes_for_tag")
    def test_edit_narrative_via_prompt(
        self, mock_get_codes, mock_checkbox, mock_text, mock_select, mock_readiness
    ):
        from hitl.theme_review import review_themes

        self._insert_draft_theme(
            1, name="ThemeA", narrative="old narrative", code_ids=[10, 11]
        )
        self._insert_mock_code(10, "CodeA", "T1")
        self._insert_mock_code(11, "CodeB", "T1")
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage, status) "
            "VALUES ('1', 'theme', 'theme', 'generated')"
        )
        mock_select.return_value.ask.return_value = "Edit"
        mock_text.return_value.ask.return_value = "new narrative"
        mock_get_codes.return_value = [
            {"id": 10, "name": "CodeA", "status": "approved"},
            {"id": 11, "name": "CodeB", "status": "approved"},
        ]
        mock_checkbox.return_value.ask.return_value = [10, 11]

        with (
            mock.patch("hitl.shared.console.print"),
            mock.patch("hitl.theme_review.get_theme_neighbors", return_value=[]),
            mock.patch("hitl.theme_review.get_constituent_codes", return_value=[]),
        ):
            review_themes(self.con, db_path=self.db_path)

        narrative = self.con.execute(
            "SELECT definition FROM nodes WHERE id = 1"
        ).fetchone()[0]
        self.assertEqual(narrative, "new narrative")
        mock_readiness.assert_called_once_with(mock.ANY, "T1", db_path=mock.ANY)

    # ── Approve fails constraint check ──────────────────────────────────

    @mock.patch("questionary.select")
    def test_approve_fails_constraint(self, mock_select):
        from hitl.theme_review import review_themes
        from ontology import ConstraintError

        self._insert_draft_theme(1, name="ThemeA", code_ids=[10])
        self._insert_mock_code(10, "CodeA", "T1")
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage, status) "
            "VALUES ('1', 'theme', 'theme', 'generated')"
        )
        mock_select.return_value.ask.return_value = "Approve"

        with (
            mock.patch("hitl.shared.console.print"),
            mock.patch("hitl.theme_review.get_theme_neighbors", return_value=[]),
            mock.patch("hitl.theme_review.get_constituent_codes", return_value=[]),
            mock.patch(
                "ontology.validate_constraint",
                side_effect=ConstraintError(
                    "CONSTRAINT_MIN_CODES",
                    "Theme has 1 code(s); at least 2 are required.",
                ),
            ),
        ):
            review_themes(self.con, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "draft")

    # ── Tag filter ──────────────────────────────────────────────────────

    @mock.patch("questionary.select")
    def test_tag_filter(self, mock_select):
        from hitl.theme_review import review_themes

        self._insert_draft_theme(1, name="T1 ThemeA", tag="T1", code_ids=[10])
        self._insert_draft_theme(2, name="T1 ThemeB", tag="T1", code_ids=[11])
        self._insert_draft_theme(3, name="T2 ThemeC", tag="T2", code_ids=[12])
        self._insert_mock_code(10, "CodeA", "T1")
        self._insert_mock_code(11, "CodeB", "T1")
        self._insert_mock_code(12, "CodeC", "T2")
        mock_select.return_value.ask.return_value = "Defer"

        with (
            mock.patch("hitl.theme_review._review_single_theme") as mock_review,
            mock.patch("hitl.shared.console.print"),
        ):
            review_themes(self.con, tag="T1", db_path=self.db_path)

        call_ids = [call.args[1]["id"] for call in mock_review.call_args_list]
        self.assertEqual(call_ids, [1, 2])

    # ── Neighbors called with k=3 ───────────────────────────────────────

    @mock.patch("questionary.select")
    def test_neighbors_called_with_k3(self, mock_select):
        from hitl.theme_review import review_themes

        self._insert_draft_theme(1, name="ThemeA", code_ids=[10, 11])
        self._insert_mock_code(10, "CodeA", "T1")
        self._insert_mock_code(11, "CodeB", "T1")
        mock_select.return_value.ask.return_value = "Defer"

        with (
            mock.patch("hitl.shared.console.print"),
            mock.patch("hitl.theme_review.get_constituent_codes", return_value=[]),
            mock.patch("hitl.theme_review.get_theme_neighbors") as mock_neighbors,
        ):
            review_themes(self.con, db_path=self.db_path)

        mock_neighbors.assert_called_once_with(mock.ANY, 1, k=3)

    # ── Approve logs constraint_type for audit ──────────────────────────

    @mock.patch("questionary.select")
    @mock.patch("hitl.theme_review_actions.logger")
    def test_approve_logs_constraint_type(self, mock_logger, mock_select):
        """Constraint approval failure logs constraint_type code in structured extra."""
        from hitl.theme_review import review_themes
        from ontology import ConstraintError

        self._insert_draft_theme(1, name="ThemeA", code_ids=[10])
        self._insert_mock_code(10, "CodeA", "T1")
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage, status) "
            "VALUES ('1', 'theme', 'theme', 'generated')"
        )
        mock_select.return_value.ask.return_value = "Approve"

        with (
            mock.patch("hitl.shared.console.print"),
            mock.patch("hitl.theme_review.get_theme_neighbors", return_value=[]),
            mock.patch("hitl.theme_review.get_constituent_codes", return_value=[]),
            mock.patch(
                "ontology.validate_constraint",
                side_effect=ConstraintError(
                    "CONSTRAINT_MIN_CODES",
                    "Theme has 1 code(s); at least 2 are required.",
                ),
            ),
        ):
            review_themes(self.con, db_path=self.db_path)

        mock_logger.warning.assert_called_once()
        _call_args = mock_logger.warning.call_args
        self.assertIn("constraint_type", _call_args[1]["extra"])
        self.assertEqual(
            _call_args[1]["extra"]["constraint_type"], "CONSTRAINT_MIN_CODES"
        )

    # ── Merge themes with different tags rejected ───────────────────────

    @mock.patch("hitl.theme_review_merge.get_node")
    def test_merge_themes_different_tags_rejected(self, mock_get_node):
        """Merging two themes with different tags raises CONSTRAINT_TAG_MISMATCH."""
        from hitl.theme_review_merge import handle_merge_themes
        from ontology.constraints import CONSTRAINT_TAG_MISMATCH, ConstraintError

        source = {
            "id": 1,
            "name": "ThemeA",
            "tag": "T1",
            "type": "theme",
            "status": "draft",
            "data_json": {},
        }
        target = {
            "id": 2,
            "name": "ThemeB",
            "tag": "T2",
            "type": "theme",
            "status": "draft",
        }
        mock_get_node.return_value = target

        with self.assertRaises(ConstraintError) as ctx:
            handle_merge_themes(self.con, source, target_id=2, db_path=self.db_path)

        self.assertEqual(ctx.exception.code, CONSTRAINT_TAG_MISMATCH)

    # ── Merge abort when no candidates ──────────────────────────────────

    @mock.patch("questionary.select")
    def test_merge_no_candidates(self, mock_select):
        from hitl.theme_review import review_themes

        self._insert_draft_theme(1, name="ThemeA", code_ids=[10, 11])
        self._insert_mock_code(10, "CodeA", "T1")
        self._insert_mock_code(11, "CodeB", "T1")
        mock_select.return_value.ask.return_value = "Merge"

        with (
            mock.patch("hitl.shared.console.print") as mock_print,
            mock.patch("hitl.theme_review.get_theme_neighbors", return_value=[]),
            mock.patch("hitl.theme_review.get_constituent_codes", return_value=[]),
        ):
            review_themes(self.con, db_path=self.db_path)

        printed = [str(c[0][0]) for c in mock_print.call_args_list]
        self.assertTrue(
            any("No other draft themes" in p for p in printed),
            msg="Expected no-candidates message",
        )


if __name__ == "__main__":
    unittest.main()
