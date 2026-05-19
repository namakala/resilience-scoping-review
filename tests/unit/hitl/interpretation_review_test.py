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

sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import duckdb
import networkx as nx
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

        with mock.patch("hitl.shared.console.print") as mock_print:
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
            with mock.patch("hitl.shared.console.print") as mock_print:
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
            mock.patch("hitl.shared.console.print"),
            mock.patch(
                "hitl.interpretation_review.get_interpretation_neighbors",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_interpretation_themes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_theme_codes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_code_exemplars",
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
            mock.patch("hitl.shared.console.print"),
            mock.patch(
                "hitl.interpretation_review.get_interpretation_neighbors",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_interpretation_themes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_theme_codes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_code_exemplars",
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
            mock.patch("hitl.shared.console.print"),
            mock.patch(
                "hitl.interpretation_review.get_interpretation_neighbors",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_interpretation_themes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_theme_codes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_code_exemplars",
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
            mock.patch("hitl.shared.console.print"),
            mock.patch(
                "hitl.interpretation_review.get_interpretation_neighbors",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_interpretation_themes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_theme_codes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_code_exemplars",
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
            mock.patch("hitl.shared.console.print"),
            mock.patch(
                "hitl.interpretation_review.get_interpretation_neighbors",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_interpretation_themes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_theme_codes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_code_exemplars",
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
        self.assertEqual(status, "approved")

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
            mock.patch("hitl.shared.console.print"),
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
            mock.patch("hitl.shared.console.print"),
            mock.patch(
                "hitl.interpretation_review.get_interpretation_neighbors",
                return_value=[],
            ),
            mock.patch("hitl.display._display_evidence_chain") as mock_display,
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
            mock.patch("hitl.shared.console.print"),
            mock.patch(
                "hitl.interpretation_review.get_interpretation_themes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_theme_codes",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_code_exemplars",
                return_value=[],
            ),
            mock.patch(
                "hitl.interpretation_review.get_interpretation_neighbors"
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

        with mock.patch("hitl.shared.console.print"):
            handle_approve_interpretation(self.con, interp, db_path=self.db_path)

        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "approved")

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


def _build_split_test_tag_dag() -> nx.DiGraph:
    """Build minimal ontology DAG for split contiguity tests.

    Hierarchy::

        Root
         +-- T1
         +-- T2
         |    +-- T2.A
         +-- T3
    """
    G = nx.DiGraph()
    tags = [
        ("Root", 0),
        ("T1", 1),
        ("T2", 1),
        ("T2.A", 2),
        ("T3", 1),
    ]
    for tag, depth in tags:
        G.add_node(tag, depth=depth)
    G.add_edge("Root", "T1")
    G.add_edge("Root", "T2")
    G.add_edge("T2", "T2.A")
    G.add_edge("Root", "T3")
    return G


class TestInterpretationReviewSplit(unittest.TestCase):
    """Tests for handle_split_interpretation() in interpretation_review_split.py."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))
        init_inference_status_table(self.con)
        import graph.singleton as singleton

        singleton._graph = None

        # Mock ontology tag DAG for contiguity checks
        self.tag_dag = _build_split_test_tag_dag()
        self._dag_patcher = mock.patch(
            "ontology.dag.get_tag_dag", return_value=self.tag_dag
        )
        self._dag_patcher.start()

    def tearDown(self):
        self._dag_patcher.stop()
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.singleton as singleton

        singleton._graph = None

    def _insert_theme(self, theme_id, name="Theme", tag="T1"):
        dj = json.dumps({"code_ids": []})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'theme', ?, ?, ?, 'approved', ?)",
            [theme_id, name, f"{name} narrative", tag, dj],
        )
        self.con.execute("SELECT nextval('nodes_id_seq')")

    def _insert_interpretation(
        self, interp_id, name="InterpA", narrative="narrative", theme_ids=None
    ):
        theme_ids = theme_ids or []
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'interpretation', ?, ?, 'T1', 'draft', '{}')",
            [interp_id, name, narrative],
        )
        self.con.execute("SELECT nextval('nodes_id_seq')")
        for tid in theme_ids:
            self.con.execute(
                "INSERT INTO edges (source_id, target_id, edge_type) "
                "VALUES (?, ?, 'spans')",
                [interp_id, tid],
            )

    def _interp_dict(self, interp_id):
        row = self.con.execute(
            "SELECT id, name, definition, tag, data_json, status "
            "FROM nodes WHERE id = ?",
            [interp_id],
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

    # ── Tests ────────────────────────────────────────────────────────

    def test_split_two_themes_creates_two_new_nodes(self):
        """Split an interpretation with 2 themes into 2 new interpretations."""
        from hitl.interpretation_review_split import handle_split_interpretation

        self._insert_interpretation(1, theme_ids=[10, 11])
        self._insert_theme(10, "ThemeA", tag="T1")
        self._insert_theme(11, "ThemeB", tag="T2")

        interp = self._interp_dict(1)

        first_id, second_id = handle_split_interpretation(
            self.con,
            interp,
            first_theme_ids=[10],
            second_theme_ids=[11],
            first_name="Interp Part 1",
            second_name="Interp Part 2",
            first_narrative="Narrative 1",
            second_narrative="Narrative 2",
            db_path=self.db_path,
        )

        # Original should be merged
        orig_status = self.con.execute(
            "SELECT status FROM nodes WHERE id = 1"
        ).fetchone()[0]
        self.assertEqual(orig_status, "merged")

        # New nodes should be draft
        first_status = self.con.execute(
            "SELECT status FROM nodes WHERE id = ?", [first_id]
        ).fetchone()[0]
        self.assertEqual(first_status, "draft")
        second_status = self.con.execute(
            "SELECT status FROM nodes WHERE id = ?", [second_id]
        ).fetchone()[0]
        self.assertEqual(second_status, "draft")

        # Check spans edges
        first_themes = self.con.execute(
            "SELECT target_id FROM edges WHERE source_id = ? AND edge_type = 'spans'",
            [first_id],
        ).fetchall()
        self.assertEqual([r[0] for r in first_themes], [10])

        second_themes = self.con.execute(
            "SELECT target_id FROM edges WHERE source_id = ? AND edge_type = 'spans'",
            [second_id],
        ).fetchall()
        self.assertEqual([r[0] for r in second_themes], [11])

        # Check derived-from edges
        derived = self.con.execute(
            "SELECT target_id FROM edges WHERE source_id = ? AND edge_type = 'derived-from'",
            [1],
        ).fetchall()
        self.assertEqual(sorted([r[0] for r in derived]), sorted([first_id, second_id]))

    def test_split_noncontiguous_tags_raises_valueerror(self):
        """Split where themes have tags from disjoint branches raises ValueError."""
        from hitl.interpretation_review_split import handle_split_interpretation

        self._insert_interpretation(1, theme_ids=[10, 11, 12])
        self._insert_theme(10, "ThemeA", tag="T1")
        self._insert_theme(11, "ThemeB", tag="T2.A")
        self._insert_theme(12, "ThemeC", tag="T3")

        interp = self._interp_dict(1)

        with self.assertRaises(ValueError) as ctx:
            handle_split_interpretation(
                self.con,
                interp,
                first_theme_ids=[10, 11],
                second_theme_ids=[12],
                first_name="Bad Split",
                second_name="Remaining",
                first_narrative="N1",
                second_narrative="N2",
                db_path=self.db_path,
            )
        self.assertIn("non-contiguous", str(ctx.exception).lower())

    def test_split_empty_theme_list_raises_valueerror(self):
        """Passing an empty first_theme_ids raises ValueError."""
        from hitl.interpretation_review_split import handle_split_interpretation

        self._insert_interpretation(1, theme_ids=[10, 11])
        self._insert_theme(10, "ThemeA")
        self._insert_theme(11, "ThemeB")

        interp = self._interp_dict(1)

        with self.assertRaises(ValueError):
            handle_split_interpretation(
                self.con,
                interp,
                first_theme_ids=[],
                second_theme_ids=[11],
                first_name="Empty",
                second_name="Rest",
                first_narrative="N1",
                second_narrative="N2",
                db_path=self.db_path,
            )

    def test_split_all_themes_to_one_side_raises_valueerror(self):
        """Passing an empty second_theme_ids raises ValueError."""
        from hitl.interpretation_review_split import handle_split_interpretation

        self._insert_interpretation(1, theme_ids=[10])
        self._insert_theme(10, "ThemeA")

        interp = self._interp_dict(1)

        with self.assertRaises(ValueError):
            handle_split_interpretation(
                self.con,
                interp,
                first_theme_ids=[10],
                second_theme_ids=[],
                first_name="All",
                second_name="None",
                first_narrative="N1",
                second_narrative="N2",
                db_path=self.db_path,
            )

    def test_split_data_json_contains_merged_info(self):
        """Original interpretation gets merged_info in data_json."""
        from hitl.interpretation_review_split import handle_split_interpretation

        self._insert_interpretation(1, theme_ids=[10, 11])
        self._insert_theme(10, "ThemeA", tag="T1")
        self._insert_theme(11, "ThemeB", tag="T2")

        interp = self._interp_dict(1)

        handle_split_interpretation(
            self.con,
            interp,
            first_theme_ids=[10],
            second_theme_ids=[11],
            first_name="Part 1",
            second_name="Part 2",
            first_narrative="N1",
            second_narrative="N2",
            db_path=self.db_path,
        )

        row = self.con.execute("SELECT data_json FROM nodes WHERE id = 1").fetchone()
        dj = json.loads(row[0]) if row[0] else {}
        self.assertIn("merged_info", dj)
        self.assertEqual(dj["merged_info"]["split_into_first_name"], "Part 1")
        self.assertEqual(dj["merged_info"]["split_into_second_name"], "Part 2")

    def test_split_action_logged(self):
        """Split action is recorded in user_actions table."""
        from hitl.interpretation_review_split import handle_split_interpretation

        self._insert_interpretation(1, theme_ids=[10, 11])
        self._insert_theme(10, "ThemeA", tag="T1")
        self._insert_theme(11, "ThemeB", tag="T2")

        interp = self._interp_dict(1)

        handle_split_interpretation(
            self.con,
            interp,
            first_theme_ids=[10],
            second_theme_ids=[11],
            first_name="Part 1",
            second_name="Part 2",
            first_narrative="N1",
            second_narrative="N2",
            db_path=self.db_path,
        )

        rows = self.con.execute(
            "SELECT action_type, entity_id FROM user_actions WHERE entity_id = 1"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "split")

    def test_split_data_json_tag_spans(self):
        """New interpretations have correct tag_spans in data_json."""
        from hitl.interpretation_review_split import handle_split_interpretation

        self._insert_interpretation(1, theme_ids=[10, 11])
        self._insert_theme(10, "ThemeA", tag="T1")
        self._insert_theme(11, "ThemeB", tag="T2")

        interp = self._interp_dict(1)

        first_id, second_id = handle_split_interpretation(
            self.con,
            interp,
            first_theme_ids=[10],
            second_theme_ids=[11],
            first_name="Part 1",
            second_name="Part 2",
            first_narrative="N1",
            second_narrative="N2",
            db_path=self.db_path,
        )

        first_dj = json.loads(
            self.con.execute(
                "SELECT data_json FROM nodes WHERE id = ?", [first_id]
            ).fetchone()[0]
            or "{}"
        )
        self.assertEqual(first_dj.get("tag_spans"), ["T1"])

        second_dj = json.loads(
            self.con.execute(
                "SELECT data_json FROM nodes WHERE id = ?", [second_id]
            ).fetchone()[0]
            or "{}"
        )
        self.assertEqual(second_dj.get("tag_spans"), ["T2"])


class TestInterpretationReviewSplitInteractive(unittest.TestCase):
    """Tests for handle_split_interactive flow in prompts_interpretations.py."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))
        init_inference_status_table(self.con)
        import graph.singleton as singleton

        singleton._graph = None

        self.tag_dag = _build_split_test_tag_dag()
        self._dag_patcher = mock.patch(
            "ontology.dag.get_tag_dag", return_value=self.tag_dag
        )
        self._dag_patcher.start()

    def tearDown(self):
        self._dag_patcher.stop()
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.singleton as singleton

        singleton._graph = None

    def _insert_theme(self, theme_id, name="Theme", tag="T1"):
        dj = json.dumps({"code_ids": []})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'theme', ?, ?, ?, 'approved', ?)",
            [theme_id, name, f"{name} narrative", tag, dj],
        )
        self.con.execute("SELECT nextval('nodes_id_seq')")

    def _insert_interpretation(
        self, interp_id, name="InterpA", narrative="narrative", theme_ids=None
    ):
        theme_ids = theme_ids or []
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'interpretation', ?, ?, 'T1', 'draft', '{}')",
            [interp_id, name, narrative],
        )
        self.con.execute("SELECT nextval('nodes_id_seq')")
        for tid in theme_ids:
            self.con.execute(
                "INSERT INTO edges (source_id, target_id, edge_type) "
                "VALUES (?, ?, 'spans')",
                [interp_id, tid],
            )

    def _interp_dict(self, interp_id):
        row = self.con.execute(
            "SELECT id, name, definition, tag, data_json, status "
            "FROM nodes WHERE id = ?",
            [interp_id],
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

    @mock.patch("questionary.checkbox")
    @mock.patch("questionary.text")
    @mock.patch("questionary.confirm")
    def test_split_interactive_happy_path(self, mock_confirm, mock_text, mock_checkbox):
        """Full interactive split flow completes successfully."""
        from hitl.prompts_interpretations import handle_split_interactive

        self._insert_interpretation(1, name="TestInterp", theme_ids=[10, 11])
        self._insert_theme(10, "ThemeA", tag="T1")
        self._insert_theme(11, "ThemeB", tag="T2")

        interp = self._interp_dict(1)

        # Simulate user selecting first theme
        mock_checkbox.return_value.ask.return_value = [10]

        # Each questionary.text() call returns a mock with .ask()
        text_responses = iter(
            ["Split Part 1", "Split Part 2", "Narrative 1", "Narrative 2"]
        )

        def _make_text_mock(*_a, **_kw):
            m = mock.MagicMock()
            m.ask.return_value = next(text_responses)
            return m

        mock_text.side_effect = _make_text_mock

        mock_confirm.return_value.ask.return_value = True

        with mock.patch("hitl.shared.console.print"):
            handle_split_interactive(self.con, interp, db_path=self.db_path)

        # Original should be merged
        orig_status = self.con.execute(
            "SELECT status FROM nodes WHERE id = 1"
        ).fetchone()[0]
        self.assertEqual(orig_status, "merged")

    @mock.patch("questionary.checkbox")
    def test_split_interactive_cancel_at_theme_selection(self, mock_checkbox):
        """Cancelling at theme selection prints message and returns."""
        from hitl.prompts_interpretations import handle_split_interactive

        self._insert_interpretation(1, name="TestInterp", theme_ids=[10, 11])
        self._insert_theme(10, "ThemeA")
        self._insert_theme(11, "ThemeB")

        interp = self._interp_dict(1)
        mock_checkbox.return_value.ask.return_value = None

        with mock.patch("hitl.shared.console.print") as mock_print:
            handle_split_interactive(self.con, interp, db_path=self.db_path)
            printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list)
            self.assertIn("cancelled", printed.lower())

        # Status unchanged
        status = self.con.execute("SELECT status FROM nodes WHERE id = 1").fetchone()[0]
        self.assertEqual(status, "draft")


class TestHandleSplitInterpretationRegroupMultiGroup(unittest.TestCase):
    """Tests for handle_split_interpretation_regroup with N groups."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))
        init_inference_status_table(self.con)
        import graph.singleton as singleton

        singleton._graph = None
        self.tag_dag = _build_split_test_tag_dag()
        self._dag_patcher = mock.patch(
            "ontology.dag.get_tag_dag", return_value=self.tag_dag
        )
        self._dag_patcher.start()

    def tearDown(self):
        self._dag_patcher.stop()
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.singleton as singleton

        singleton._graph = None

    def _insert_theme(self, theme_id, name="Theme", tag="T1"):
        dj = json.dumps({"code_ids": []})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'theme', ?, ?, ?, 'approved', ?)",
            [theme_id, name, f"{name} narrative", tag, dj],
        )
        self.con.execute("SELECT nextval('nodes_id_seq')")

    def _insert_interpretation(
        self, interp_id, name="InterpA", narrative="narrative", theme_ids=None
    ):
        theme_ids = theme_ids or []
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'interpretation', ?, ?, 'T1', 'draft', '{}')",
            [interp_id, name, narrative],
        )
        self.con.execute("SELECT nextval('nodes_id_seq')")
        for tid in theme_ids:
            self.con.execute(
                "INSERT INTO edges (source_id, target_id, edge_type) "
                "VALUES (?, ?, 'spans')",
                [interp_id, tid],
            )

    def _interp_dict(self, interp_id):
        row = self.con.execute(
            "SELECT id, name, definition, tag, data_json, status "
            "FROM nodes WHERE id = ?",
            [interp_id],
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

    def test_regroup_three_groups(self):
        """3-group interpretation split creates 3 new nodes."""
        from hitl.interpretation_review_split import handle_split_interpretation_regroup
        from inference.parsing import InterpretationInference

        self._insert_interpretation(1, theme_ids=[10, 11, 12])
        self._insert_theme(10, "ThemeA", tag="T1")
        self._insert_theme(11, "ThemeB", tag="T2")
        self._insert_theme(12, "ThemeC", tag="T3")

        interp = self._interp_dict(1)

        mock_results = [
            InterpretationInference(
                interpretation_name="Alpha Insights",
                narrative="Narrative A",
                theme_ids=["10"],
                key_insights=["k1"],
            ),
            InterpretationInference(
                interpretation_name="Beta Synthesis",
                narrative="Narrative B",
                theme_ids=["11"],
                key_insights=["k2"],
            ),
            InterpretationInference(
                interpretation_name="Gamma Findings",
                narrative="Narrative C",
                theme_ids=["12"],
                key_insights=["k3"],
            ),
        ]

        with mock.patch(
            "hitl.interpretation_review_split._infer_interpretation_for_group",
            side_effect=mock_results,
        ):
            node_ids = handle_split_interpretation_regroup(
                self.con,
                interp,
                groups=[[10], [11], [12]],
                db_path=self.db_path,
            )

        self.assertEqual(len(node_ids), 3)

        orig_status = self.con.execute(
            "SELECT status FROM nodes WHERE id = 1"
        ).fetchone()[0]
        self.assertEqual(orig_status, "superseded")

        row = self.con.execute("SELECT data_json FROM nodes WHERE id = 1").fetchone()
        dj = json.loads(row[0]) if row[0] else {}
        self.assertEqual(dj["merged_info"]["split_groups"], [[10], [11], [12]])

        for nid in node_ids:
            status = self.con.execute(
                "SELECT status FROM nodes WHERE id = ?", [nid]
            ).fetchone()[0]
            self.assertEqual(status, "draft")

        for i, nid in enumerate(node_ids):
            themes = self.con.execute(
                "SELECT target_id FROM edges WHERE source_id = ? AND edge_type = 'spans'",
                [nid],
            ).fetchall()
            self.assertEqual([r[0] for r in themes], [[10], [11], [12]][i])

        derived = self.con.execute(
            "SELECT target_id FROM edges WHERE source_id = ? AND edge_type = 'derived-from'",
            [1],
        ).fetchall()
        self.assertEqual(sorted([r[0] for r in derived]), sorted(node_ids))

    def test_regroup_too_few_groups_raises_valueerror(self):
        """Fewer than 2 groups raises ValueError."""
        from hitl.interpretation_review_split import handle_split_interpretation_regroup

        self._insert_interpretation(1, theme_ids=[10, 11])
        self._insert_theme(10, "ThemeA")
        self._insert_theme(11, "ThemeB")
        interp = self._interp_dict(1)

        with self.assertRaises(ValueError):
            handle_split_interpretation_regroup(
                self.con,
                interp,
                groups=[[10]],
                db_path=self.db_path,
            )

    def test_regroup_empty_group_raises_valueerror(self):
        """An empty group inside a split raises ValueError."""
        from hitl.interpretation_review_split import handle_split_interpretation_regroup

        self._insert_interpretation(1, theme_ids=[10, 11])
        self._insert_theme(10, "ThemeA")
        self._insert_theme(11, "ThemeB")
        interp = self._interp_dict(1)

        with self.assertRaises(ValueError):
            handle_split_interpretation_regroup(
                self.con,
                interp,
                groups=[[10], []],
                db_path=self.db_path,
            )


class TestHandleSplitCodeRegroupMultiGroup(unittest.TestCase):
    """Tests for handle_split_code_regroup with N groups."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))
        init_inference_status_table(self.con)
        import graph.singleton as singleton
        from inference.inference_status_crud import set_status
        from inference.inference_status_types import (
            ENTITY_EXEMPLAR,
            PENDING,
            STAGE_CODE,
        )

        singleton._graph = None

    def tearDown(self):
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        import graph.singleton as singleton

        singleton._graph = None

    def _make_code(self, code_id, tag="T1", exemplar_ids=None):
        exemplar_ids = exemplar_ids or []
        dj = json.dumps({"exemplar_ids": exemplar_ids})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'code', ?, ?, ?, 'draft', ?)",
            [code_id, f"Code{code_id}", f"Definition {code_id}", tag, dj],
        )
        self.con.execute("SELECT nextval('nodes_id_seq')")
        for eid in exemplar_ids:
            self.con.execute(
                "INSERT INTO edges (source_id, target_id, edge_type) "
                "VALUES (?, ?, 'contains')",
                [code_id, eid],
            )

    def _code_dict(self, code_id):
        row = self.con.execute(
            "SELECT id, name, definition, tag, data_json, status "
            "FROM nodes WHERE id = ?",
            [code_id],
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

    def test_code_split_three_groups_validates_merged_info(self):
        """3-group code split stores all groups in merged_info."""
        from hitl.code_review_split import handle_split_code_regroup
        from inference.parsing import CodeInference

        self._make_code(1, exemplar_ids=[100, 200, 300])
        code = self._code_dict(1)

        mock_codes = [
            CodeInference(
                exemplar_id="100",
                code_name="CodeA",
                definition="DefA",
                supporting_quote="Q1",
                tag="T1",
            ),
            CodeInference(
                exemplar_id="200",
                code_name="CodeB",
                definition="DefB",
                supporting_quote="Q2",
                tag="T1",
            ),
            CodeInference(
                exemplar_id="300",
                code_name="CodeC",
                definition="DefC",
                supporting_quote="Q3",
                tag="T1",
            ),
        ]

        with (
            mock.patch("hitl.code_review_split.infer_codes", return_value=mock_codes),
            mock.patch(
                "hitl.code_review_split.create_code_nodes", return_value=[101, 102, 103]
            ),
            mock.patch("hitl.code_review_split.generate_code_embeddings"),
            mock.patch("hitl.code_review_split.invalidate_themes", return_value=[]),
            mock.patch("hitl.code_review_split.invalidate_interpretations"),
            mock.patch("hitl.code_review_split.increment_user_action_count"),
            mock.patch("hitl.code_review_split.log_user_action"),
        ):
            node_ids = handle_split_code_regroup(
                self.con,
                code,
                groups=[[100], [200], [300]],
                db_path=self.db_path,
            )

        self.assertEqual(node_ids, [101, 102, 103])

        row = self.con.execute(
            "SELECT status, data_json FROM nodes WHERE id = 1"
        ).fetchone()
        self.assertEqual(row[0], "superseded")
        dj = json.loads(row[1]) if row[1] else {}
        self.assertEqual(dj["merged_info"]["split_groups"], [[100], [200], [300]])

    def test_code_split_too_few_groups_raises_valueerror(self):
        """Fewer than 2 groups raises ValueError for code split."""
        from hitl.code_review_split import handle_split_code_regroup

        self._make_code(1, exemplar_ids=[100, 200])
        code = self._code_dict(1)

        with self.assertRaises(ValueError):
            handle_split_code_regroup(
                self.con,
                code,
                groups=[[100]],
                db_path=self.db_path,
            )

    def test_code_split_empty_group_raises_valueerror(self):
        """Empty group raises ValueError for code split."""
        from hitl.code_review_split import handle_split_code_regroup

        self._make_code(1, exemplar_ids=[100, 200])
        code = self._code_dict(1)

        with self.assertRaises(ValueError):
            handle_split_code_regroup(
                self.con,
                code,
                groups=[[100], []],
                db_path=self.db_path,
            )


class TestHandleSplitThemeRegroupMultiGroup(unittest.TestCase):
    """Tests for handle_split_theme_regroup with N groups."""

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

    def _make_theme(self, theme_id, tag="T1", code_ids=None):
        code_ids = code_ids or []
        dj = json.dumps({"code_ids": code_ids})
        self.con.execute(
            "INSERT INTO nodes (id, type, name, definition, tag, status, data_json) "
            "VALUES (?, 'theme', ?, ?, ?, 'draft', ?)",
            [theme_id, f"Theme{theme_id}", f"Narrative {theme_id}", tag, dj],
        )
        self.con.execute("SELECT nextval('nodes_id_seq')")
        for cid in code_ids:
            self.con.execute(
                "INSERT INTO edges (source_id, target_id, edge_type) "
                "VALUES (?, ?, 'composed-of')",
                [theme_id, cid],
            )

    def _theme_dict(self, theme_id):
        row = self.con.execute(
            "SELECT id, name, definition, tag, data_json, status "
            "FROM nodes WHERE id = ?",
            [theme_id],
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

    def test_theme_split_three_groups_validates_merged_info(self):
        """3-group theme split stores all groups in merged_info."""
        from hitl.theme_review_split import handle_split_theme_regroup
        from inference.parsing import ThemeInference

        self._make_theme(1, code_ids=[10, 20, 30])
        theme = self._theme_dict(1)

        mock_themes = [
            ThemeInference(
                theme_name="SubThemeA", narrative="Na", code_ids=["10"], tag="T1"
            ),
            ThemeInference(
                theme_name="SubThemeB", narrative="Nb", code_ids=["20"], tag="T1"
            ),
            ThemeInference(
                theme_name="SubThemeC", narrative="Nc", code_ids=["30"], tag="T1"
            ),
        ]

        with (
            mock.patch(
                "hitl.theme_review_split.infer_themes", return_value=mock_themes
            ),
            mock.patch(
                "hitl.theme_review_split.create_theme_nodes",
                return_value=[101, 102, 103],
            ),
            mock.patch("hitl.theme_review_split.generate_theme_embeddings"),
            mock.patch("hitl.theme_review_split.invalidate_interpretations"),
            mock.patch("hitl.theme_review_split.increment_user_action_count"),
            mock.patch("hitl.theme_review_split.log_user_action"),
        ):
            node_ids = handle_split_theme_regroup(
                self.con,
                theme,
                groups=[[10], [20], [30]],
                db_path=self.db_path,
            )

        self.assertEqual(node_ids, [101, 102, 103])

        row = self.con.execute(
            "SELECT status, data_json FROM nodes WHERE id = 1"
        ).fetchone()
        self.assertEqual(row[0], "superseded")
        dj = json.loads(row[1]) if row[1] else {}
        self.assertEqual(dj["merged_info"]["split_groups"], [[10], [20], [30]])

    def test_theme_split_too_few_groups_raises_valueerror(self):
        """Fewer than 2 groups raises ValueError for theme split."""
        from hitl.theme_review_split import handle_split_theme_regroup

        self._make_theme(1, code_ids=[10, 20])
        theme = self._theme_dict(1)

        with self.assertRaises(ValueError):
            handle_split_theme_regroup(
                self.con,
                theme,
                groups=[[10]],
                db_path=self.db_path,
            )

    def test_theme_split_empty_group_raises_valueerror(self):
        """Empty group raises ValueError for theme split."""
        from hitl.theme_review_split import handle_split_theme_regroup

        self._make_theme(1, code_ids=[10, 20])
        theme = self._theme_dict(1)

        with self.assertRaises(ValueError):
            handle_split_theme_regroup(
                self.con,
                theme,
                groups=[[10], []],
                db_path=self.db_path,
            )


if __name__ == "__main__":
    unittest.main()
