"""Tests for interpretation review CLI orchestration and action handlers.

Tests the full orchestration flow (with mocked prompts) and direct action
handler calls (without prompts).
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


class TestInterpretationReviewOrchestration(unittest.TestCase):
    """Tests for review_interpretations() entry point with mocked prompts."""

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

    def _insert_draft_interpretation(
        self,
        interp_id,
        name="InterpA",
        narrative="test narrative",
        tag="T1",
        theme_ids=None,
        tag_spans=None,
    ):
        theme_ids = theme_ids or []
        tag_spans = tag_spans or ["T1"]
        dj = json.dumps({"tag_spans": tag_spans})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'interpretation', ?, ?, ?, 'draft', ?)",
            [interp_id, name, narrative, tag, dj],
        )
        for tid in theme_ids:
            self.con.execute(
                "INSERT INTO edges (source_id, target_id, edge_type) "
                "VALUES (?, ?, 'spans')",
                [interp_id, tid],
            )

    def _insert_theme(
        self,
        theme_id,
        name="ThemeA",
        narrative="theme narrative",
        tag="T1",
        code_ids=None,
        status="approved",
    ):
        code_ids = code_ids or []
        dj = json.dumps({"code_ids": code_ids})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'theme', ?, ?, ?, ?, ?)",
            [theme_id, name, narrative, tag, status, dj],
        )
        for cid in code_ids:
            self.con.execute(
                "INSERT INTO edges (source_id, target_id, edge_type) "
                "VALUES (?, ?, 'composed-of')",
                [theme_id, cid],
            )

    def _insert_code(
        self,
        code_id,
        name="CodeA",
        tag="T1",
        exemplar_ids=None,
    ):
        exemplar_ids = exemplar_ids or []
        dj = json.dumps({"exemplar_ids": [str(e) for e in exemplar_ids]})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'code', ?, ?, ?, 'approved', ?)",
            [code_id, name, f"Definition for {name}", tag, dj],
        )
        for eid in exemplar_ids:
            self.con.execute(
                "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
                "VALUES (?, 'exemplar', ?, ?, ?, 'immutable', '{}')",
                [eid, f"ex_{eid}", f"Exemplar content {eid}", tag],
            )
            self.con.execute(
                "INSERT INTO edges (source_id, target_id, edge_type) "
                "VALUES (?, ?, 'contains')",
                [code_id, eid],
            )

    # ── No pending interpretations ──────────────────────────────────────

    def test_no_pending_interpretations_returns_early(self):
        from hitl.interpretation_review import review_interpretations

        with mock.patch(
            "hitl.interpretation_review_display.console.print"
        ) as mock_print:
            review_interpretations(self.con, db_path=self.db_path)
            mock_print.assert_called_once()
            msg = str(mock_print.call_args[0][0])
            self.assertIn("No pending interpretations", msg)

    # ── Keyboard interrupt ──────────────────────────────────────────────

    def test_keyboard_interrupt_graceful(self):
        from hitl.interpretation_review import review_interpretations

        self._insert_draft_interpretation(1)
        with mock.patch(
            "hitl.interpretation_review._review_single_interpretation",
            side_effect=KeyboardInterrupt(),
        ):
            with mock.patch(
                "hitl.interpretation_review_display.console.print"
            ) as mock_print:
                review_interpretations(self.con, db_path=self.db_path)
                printed = [str(c[0][0]) for c in mock_print.call_args_list]
                self.assertTrue(any("interrupted" in p.lower() for p in printed))

    # ── Approve via prompt ──────────────────────────────────────────────

    @mock.patch("ontology.validate_constraint")
    @mock.patch("questionary.select")
    def test_approve_via_prompt(self, mock_select, mock_constraint):
        from hitl.interpretation_review import review_interpretations

        self._insert_draft_interpretation(
            1, name="InterpA", theme_ids=[10, 11], tag_spans=["T1", "T2"]
        )
        self._insert_theme(10, "ThemeA", tag="T1")
        self._insert_theme(11, "ThemeB", tag="T2")
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage, status) "
            "VALUES ('1', 'interpretation', 'interpretation', 'generated')"
        )
        mock_select.return_value.ask.return_value = "Approve"
        mock_constraint.return_value = None

        with (
            mock.patch("hitl.interpretation_review_display.console.print"),
            mock.patch(
                "hitl.interpretation_review._get_interpretation_neighbors",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_interpretation_themes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_theme_codes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_code_exemplars",
                return_value=[],
            ),
        ):
            review_interpretations(self.con, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "approved")

    # ── Reject via prompt ───────────────────────────────────────────────

    @mock.patch("questionary.select")
    def test_reject_via_prompt(self, mock_select):
        from hitl.interpretation_review import review_interpretations

        self._insert_draft_interpretation(1, name="InterpA", theme_ids=[10, 11])
        self._insert_theme(10, "ThemeA", tag="T1")
        self._insert_theme(11, "ThemeB", tag="T2")
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage, status) "
            "VALUES ('1', 'interpretation', 'interpretation', 'generated')"
        )
        mock_select.return_value.ask.return_value = "Reject"

        with (
            mock.patch("hitl.interpretation_review_display.console.print"),
            mock.patch(
                "hitl.interpretation_review._get_interpretation_neighbors",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_interpretation_themes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_theme_codes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_code_exemplars",
                return_value=[],
            ),
        ):
            review_interpretations(self.con, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "rejected")

    # ── Defer via prompt ────────────────────────────────────────────────

    @mock.patch("questionary.select")
    def test_defer_via_prompt(self, mock_select):
        from hitl.interpretation_review import review_interpretations

        self._insert_draft_interpretation(1, name="InterpA", theme_ids=[10])
        self._insert_theme(10, "ThemeA", tag="T1")
        mock_select.return_value.ask.return_value = "Defer"

        with (
            mock.patch("hitl.interpretation_review_display.console.print"),
            mock.patch(
                "hitl.interpretation_review._get_interpretation_neighbors",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_interpretation_themes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_theme_codes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_code_exemplars",
                return_value=[],
            ),
        ):
            review_interpretations(self.con, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "draft")

    # ── Edit narrative via prompt ───────────────────────────────────────

    @mock.patch("questionary.select")
    @mock.patch("questionary.text")
    def test_edit_narrative_via_prompt(self, mock_text, mock_select):
        from hitl.interpretation_review import review_interpretations

        self._insert_draft_interpretation(
            1,
            name="InterpA",
            narrative="old narrative",
            theme_ids=[10],
            tag_spans=["T1"],
        )
        self._insert_theme(10, "ThemeA", tag="T1")
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage, status) "
            "VALUES ('1', 'interpretation', 'interpretation', 'generated')"
        )
        mock_select.return_value.ask.return_value = "Edit"
        mock_text.return_value.ask.return_value = "new narrative"

        with (
            mock.patch("hitl.interpretation_review_display.console.print"),
            mock.patch(
                "hitl.interpretation_review._get_interpretation_neighbors",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_interpretation_themes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_theme_codes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_code_exemplars",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review_actions.invalidate_interpretation_embedding"
            ),
        ):
            review_interpretations(self.con, db_path=self.db_path)

        narrative = self.con.execute(
            "SELECT definition FROM nodes WHERE id = 1"
        ).fetchone()[0]
        self.assertEqual(narrative, "new narrative")

    # ── Approve fails constraint check ──────────────────────────────────

    @mock.patch("questionary.select")
    def test_approve_fails_constraint(self, mock_select):
        from hitl.interpretation_review import review_interpretations
        from ontology import ConstraintError

        self._insert_draft_interpretation(
            1, name="InterpA", theme_ids=[10, 11], tag_spans=["T1", "T2"]
        )
        self._insert_theme(10, "ThemeA", tag="T1")
        self._insert_theme(11, "ThemeB", tag="T2")
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage, status) "
            "VALUES ('1', 'interpretation', 'interpretation', 'generated')"
        )
        mock_select.return_value.ask.return_value = "Approve"

        with (
            mock.patch("hitl.interpretation_review_display.console.print"),
            mock.patch(
                "hitl.interpretation_review._get_interpretation_neighbors",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_interpretation_themes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_theme_codes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_code_exemplars",
                return_value=[],
            ),
            mock.patch(
                "ontology.validate_constraint",
                side_effect=ConstraintError(
                    "CONSTRAINT_NONCONTIGUOUS_SPAN",
                    "Tags do not form a contiguous subtree.",
                ),
            ),
        ):
            review_interpretations(self.con, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "draft")

    # ── Tag filter ──────────────────────────────────────────────────────

    @mock.patch("questionary.select")
    def test_tag_filter(self, mock_select):
        from hitl.interpretation_review import review_interpretations

        self._insert_draft_interpretation(
            1, name="InterpA", tag="T1", theme_ids=[10], tag_spans=["T1"]
        )
        self._insert_draft_interpretation(
            2, name="InterpB", tag="T1", theme_ids=[11], tag_spans=["T1"]
        )
        self._insert_draft_interpretation(
            3, name="InterpC", tag="T2", theme_ids=[12], tag_spans=["T2"]
        )
        self._insert_theme(10, "ThemeA", tag="T1")
        self._insert_theme(11, "ThemeB", tag="T1")
        self._insert_theme(12, "ThemeC", tag="T2")
        mock_select.return_value.ask.return_value = "Defer"

        with (
            mock.patch(
                "hitl.interpretation_review._review_single_interpretation"
            ) as mock_review,
            mock.patch("hitl.interpretation_review_display.console.print"),
        ):
            review_interpretations(self.con, tag="T1", db_path=self.db_path)

        call_ids = [call.args[1]["id"] for call in mock_review.call_args_list]
        self.assertEqual(call_ids, [1, 2])

    # ── Evidence chain display ──────────────────────────────────────────

    @mock.patch("questionary.select")
    def test_evidence_chain_displayed(self, mock_select):
        """Verify that theme, code, and exemplar queries are called for display."""
        from hitl.interpretation_review import review_interpretations

        self._insert_draft_interpretation(
            1, name="InterpA", theme_ids=[10], tag_spans=["T1"]
        )
        self._insert_theme(10, "ThemeA", tag="T1", code_ids=[100])
        self._insert_code(100, "CodeA", tag="T1", exemplar_ids=[1000])
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage, status) "
            "VALUES ('1', 'interpretation', 'interpretation', 'generated')"
        )
        mock_select.return_value.ask.return_value = "Defer"

        with (
            mock.patch("hitl.interpretation_review_display.console.print"),
            mock.patch(
                "hitl.interpretation_review._get_interpretation_neighbors",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review_display._display_evidence_chain"
            ) as mock_display,
        ):
            review_interpretations(self.con, db_path=self.db_path)

        mock_display.assert_called_once()

    # ── Neighbors called with k=3 ───────────────────────────────────────

    @mock.patch("questionary.select")
    def test_neighbors_called_with_k3(self, mock_select):
        from hitl.interpretation_review import review_interpretations

        self._insert_draft_interpretation(1, name="InterpA", theme_ids=[10])
        self._insert_theme(10, "ThemeA", tag="T1")
        mock_select.return_value.ask.return_value = "Defer"

        with (
            mock.patch("hitl.interpretation_review_display.console.print"),
            mock.patch(
                "hitl.interpretation_review._get_interpretation_themes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_theme_codes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_code_exemplars",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review._get_interpretation_neighbors"
            ) as mock_neighbors,
        ):
            review_interpretations(self.con, db_path=self.db_path)

        mock_neighbors.assert_called_once_with(mock.ANY, 1, k=3)


class TestInterpretationReviewActions(unittest.TestCase):
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

    # ── Fixtures ────────────────────────────────────────────────────────

    def _create_interpretation(
        self,
        node_id,
        name="InterpA",
        narrative="narrative",
        tag="T1",
        tag_spans=None,
        status="draft",
    ):
        tag_spans = tag_spans or ["T1"]
        dj = json.dumps({"tag_spans": tag_spans})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'interpretation', ?, ?, ?, ?, ?)",
            [node_id, name, narrative, tag, status, dj],
        )
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage, status) "
            "VALUES (?, 'interpretation', 'interpretation', 'generated')",
            [str(node_id)],
        )

    def _interp_dict(self, node_id):
        row = self.con.execute(
            "SELECT id, name, definition, tag, data_json, status "
            "FROM nodes WHERE id = ?",
            [node_id],
        ).fetchone()
        dj = json.loads(row[4]) if row[4] else {}
        return {
            "id": row[0],
            "name": row[1],
            "narrative": row[2],
            "tag": row[3],
            "data_json": dj,
            "status": row[5],
        }

    # ── Approve ─────────────────────────────────────────────────────────

    @mock.patch("ontology.validate_constraint")
    def test_handle_approve(self, mock_constraint):
        from hitl.interpretation_review_actions import handle_approve_interpretation

        self._create_interpretation(1, tag_spans=["T1", "T2"])
        interp = self._interp_dict(1)
        mock_constraint.return_value = None

        handle_approve_interpretation(self.con, interp, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "approved")

    # ── Approve fails constraint ────────────────────────────────────────

    @mock.patch("ontology.validate_constraint")
    def test_handle_approve_constraint_failure(self, mock_constraint):
        from hitl.interpretation_review_actions import handle_approve_interpretation
        from ontology import ConstraintError

        self._create_interpretation(1, tag_spans=["T1", "T2"])
        interp = self._interp_dict(1)
        mock_constraint.side_effect = ConstraintError(
            "CONSTRAINT_NONCONTIGUOUS_SPAN",
            "Tags do not form a contiguous subtree.",
        )

        with mock.patch("hitl.interpretation_review_display.console.print"):
            handle_approve_interpretation(self.con, interp, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "draft")

    # ── Edit ────────────────────────────────────────────────────────────

    @mock.patch(
        "hitl.interpretation_review_actions.invalidate_interpretation_embedding"
    )
    def test_handle_edit(self, mock_invalidate):
        from hitl.interpretation_review_actions import handle_edit_interpretation

        self._create_interpretation(1, narrative="old narrative", tag_spans=["T1"])
        interp = self._interp_dict(1)

        handle_edit_interpretation(
            self.con, interp, db_path=self.db_path, new_narrative="new narrative"
        )

        row = self.con.execute(
            "SELECT definition, status FROM nodes WHERE id = 1"
        ).fetchone()
        self.assertEqual(row[0], "new narrative")
        self.assertEqual(row[1], "draft")
        mock_invalidate.assert_called_once()

    def test_handle_edit_empty_rejected(self):
        from hitl.interpretation_review_actions import handle_edit_interpretation

        self._create_interpretation(1, narrative="narrative", tag_spans=["T1"])
        interp = self._interp_dict(1)

        handle_edit_interpretation(
            self.con, interp, db_path=self.db_path, new_narrative="  "
        )

        narrative = self.con.execute(
            "SELECT definition FROM nodes WHERE id = 1"
        ).fetchone()[0]
        self.assertEqual(narrative, "narrative")

    def test_handle_edit_unchanged_rejected(self):
        from hitl.interpretation_review_actions import handle_edit_interpretation

        self._create_interpretation(1, narrative="same", tag_spans=["T1"])
        interp = self._interp_dict(1)

        handle_edit_interpretation(
            self.con, interp, db_path=self.db_path, new_narrative="same"
        )

        narrative = self.con.execute(
            "SELECT definition FROM nodes WHERE id = 1"
        ).fetchone()[0]
        self.assertEqual(narrative, "same")

    # ── Reject ──────────────────────────────────────────────────────────

    def test_handle_reject(self):
        from hitl.interpretation_review_actions import handle_reject_interpretation

        self._create_interpretation(1)
        interp = self._interp_dict(1)

        handle_reject_interpretation(self.con, interp, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "rejected")

    # ── Defer ───────────────────────────────────────────────────────────

    def test_handle_defer(self):
        from hitl.interpretation_review_actions import handle_defer_interpretation

        self._create_interpretation(1)
        interp = self._interp_dict(1)

        handle_defer_interpretation(self.con, interp)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "draft")


if __name__ == "__main__":
    unittest.main()
