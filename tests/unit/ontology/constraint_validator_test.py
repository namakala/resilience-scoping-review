"""Unit tests for constraint validator (Feature 21).

Test coverage:
- ConstraintError class: inheritance, attributes, string format
- Rule 1: code -> one theme on approval
- Rule 2: theme >= 2 codes, same tag on approval
- Rule 3: theme -> one interpretation on approval
- Rule 4: interpretation tag_spans contiguous subtree
- Rule 5: tag exists in ontology
- Rule 6: no cycles after merge
- Dispatch: unknown action, unknown entity type
- is_contiguous_subtree: various topology cases
"""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path

sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import networkx as nx
from ontology.constraints import (
    CONSTRAINT_CODE_MULTI_THEME,
    CONSTRAINT_CYCLE_AFTER_MERGE,
    CONSTRAINT_MIN_CODES,
    CONSTRAINT_NONCONTIGUOUS_SPAN,
    CONSTRAINT_THEME_MULTI_INTERP,
    CONSTRAINT_UNKNOWN_TAG,
    ConstraintError,
    is_contiguous_subtree,
    validate_constraint,
)
from ontology.contiguity import _missing_intermediates

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

# Standard ontology tree:
#     Problem            depth 0
#     +-- Problem.Cause  depth 1
#     |   +-- Problem.Cause.Scope   depth 2
#     +-- Problem.Solution          depth 1
#     +-- Problem.Impact            depth 1
#         +-- Problem.Impact.Scope  depth 2


def _make_tag_dag() -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_node("Problem", depth=0)
    G.add_node("Problem.Cause", depth=1)
    G.add_node("Problem.Cause.Scope", depth=2)
    G.add_node("Problem.Solution", depth=1)
    G.add_node("Problem.Impact", depth=1)
    G.add_node("Problem.Impact.Scope", depth=2)
    G.add_edge("Problem", "Problem.Cause")
    G.add_edge("Problem.Cause", "Problem.Cause.Scope")
    G.add_edge("Problem", "Problem.Solution")
    G.add_edge("Problem", "Problem.Impact")
    G.add_edge("Problem.Impact", "Problem.Impact.Scope")
    return G


def _make_chain_dag() -> nx.DiGraph:
    """A -> A.B -> A.B.C"""
    G = nx.DiGraph()
    G.add_node("A", depth=0)
    G.add_node("A.B", depth=1)
    G.add_node("A.B.C", depth=2)
    G.add_edge("A", "A.B")
    G.add_edge("A.B", "A.B.C")
    return G


def _make_disjoint_tag_dag() -> nx.DiGraph:
    """Two roots: X and Y (no path between them)."""
    G = nx.DiGraph()
    G.add_node("X", depth=0)
    G.add_node("X.X1", depth=1)
    G.add_node("Y", depth=0)
    G.add_node("Y.Y1", depth=1)
    G.add_edge("X", "X.X1")
    G.add_edge("Y", "Y.Y1")
    return G


def _make_graph_with_nodes(
    nodes: list[dict],
    edges: list[tuple[int, int, str]],
) -> nx.DiGraph:
    """Build a DiGraph with typed nodes and labeled edges."""
    G = nx.DiGraph()
    for n in nodes:
        nid = n["id"]
        attrs = {k: v for k, v in n.items() if k != "id"}
        G.add_node(nid, **attrs)
    for src, tgt, etype in edges:
        G.add_edge(src, tgt, type=etype)
    return G


# ---------------------------------------------------------------------------
# ConstraintError
# ---------------------------------------------------------------------------


class TestConstraintError(unittest.TestCase):
    """ConstraintError must be a ValueError subclass with code + message."""

    def test_is_value_error_subclass(self):
        self.assertTrue(issubclass(ConstraintError, ValueError))

    def test_has_code_and_message(self):
        err = ConstraintError("TEST_CODE", "Something went wrong")
        self.assertEqual(err.code, "TEST_CODE")
        self.assertIn("TEST_CODE", str(err))
        self.assertIn("Something went wrong", str(err))

    def test_string_representation(self):
        err = ConstraintError("CODE", "msg")
        self.assertEqual(str(err), "CODE: msg")


# ---------------------------------------------------------------------------
# Rule 1: code -> one theme upon approval
# ---------------------------------------------------------------------------


class TestRule1CodeOneTheme(unittest.TestCase):
    """Rule 1: a code must belong to at most one approved theme."""

    def setUp(self):
        self.tag_dag = _make_tag_dag()

    def test_code_not_in_any_theme_approves(self):
        """Code with no composed-of edge -> OK."""
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "code",
                    "name": "C1",
                    "tag": "Problem",
                    "status": "draft",
                }
            ],
            [],
        )
        validate_constraint(
            {"id": 1, "type": "code", "tag": "Problem"},
            "approve",
            graph=G,
            tag_dag=self.tag_dag,
        )

    def test_code_in_draft_theme_approves(self):
        """Code linked to a draft (not yet approved) theme -> OK."""
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "code",
                    "name": "C1",
                    "tag": "Problem",
                    "status": "draft",
                },
                {
                    "id": 2,
                    "type": "theme",
                    "name": "T1",
                    "tag": "Problem",
                    "status": "draft",
                },
            ],
            [(2, 1, "composed-of")],
        )
        validate_constraint(
            {"id": 1, "type": "code", "tag": "Problem"},
            "approve",
            graph=G,
            tag_dag=self.tag_dag,
        )

    def test_code_in_approved_theme_rejected(self):
        """Code in an approved theme -> CONSTRAINT_CODE_MULTI_THEME."""
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "code",
                    "name": "C1",
                    "tag": "Problem",
                    "status": "approved",
                },
                {
                    "id": 2,
                    "type": "theme",
                    "name": "T1",
                    "tag": "Problem",
                    "status": "approved",
                },
            ],
            [(2, 1, "composed-of")],
        )
        with self.assertRaises(ConstraintError) as ctx:
            validate_constraint(
                {"id": 1, "type": "code", "tag": "Problem"},
                "approve",
                graph=G,
                tag_dag=self.tag_dag,
            )
        self.assertEqual(ctx.exception.code, CONSTRAINT_CODE_MULTI_THEME)

    def test_code_in_merged_theme_approves(self):
        """Code linked to a merged theme (inactive) -> OK."""
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "code",
                    "name": "C1",
                    "tag": "Problem",
                    "status": "approved",
                },
                {
                    "id": 2,
                    "type": "theme",
                    "name": "T1",
                    "tag": "Problem",
                    "status": "merged",
                },
            ],
            [(2, 1, "composed-of")],
        )
        validate_constraint(
            {"id": 1, "type": "code", "tag": "Problem"},
            "approve",
            graph=G,
            tag_dag=self.tag_dag,
        )


# ---------------------------------------------------------------------------
# Rule 2: theme >= 2 codes, all same tag
# ---------------------------------------------------------------------------


class TestRule2ThemeMinimumCodesSameTag(unittest.TestCase):
    """Rule 2: theme approval requires >= 2 codes all with identical tag."""

    def setUp(self):
        self.tag_dag = _make_tag_dag()

    def test_theme_with_two_codes_same_tag_approves(self):
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "theme",
                    "name": "T1",
                    "tag": "Problem",
                    "status": "draft",
                },
                {
                    "id": 10,
                    "type": "code",
                    "name": "C1",
                    "tag": "Problem",
                    "status": "approved",
                },
                {
                    "id": 11,
                    "type": "code",
                    "name": "C2",
                    "tag": "Problem",
                    "status": "approved",
                },
            ],
            [(1, 10, "composed-of"), (1, 11, "composed-of")],
        )
        validate_constraint(
            {"id": 1, "type": "theme", "tag": "Problem"},
            "approve",
            graph=G,
            tag_dag=self.tag_dag,
        )

    def test_theme_with_one_code_rejected(self):
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "theme",
                    "name": "T1",
                    "tag": "Problem",
                    "status": "draft",
                },
                {
                    "id": 10,
                    "type": "code",
                    "name": "C1",
                    "tag": "Problem",
                    "status": "approved",
                },
            ],
            [(1, 10, "composed-of")],
        )
        with self.assertRaises(ConstraintError) as ctx:
            validate_constraint(
                {"id": 1, "type": "theme", "tag": "Problem"},
                "approve",
                graph=G,
                tag_dag=self.tag_dag,
            )
        self.assertEqual(ctx.exception.code, CONSTRAINT_MIN_CODES)

    def test_theme_with_zero_codes_rejected(self):
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "theme",
                    "name": "T1",
                    "tag": "Problem",
                    "status": "draft",
                }
            ],
            [],
        )
        with self.assertRaises(ConstraintError) as ctx:
            validate_constraint(
                {"id": 1, "type": "theme", "tag": "Problem"},
                "approve",
                graph=G,
                tag_dag=self.tag_dag,
            )
        self.assertEqual(ctx.exception.code, CONSTRAINT_MIN_CODES)

    def test_theme_with_codes_from_different_tags_allowed(self):
        """Theme with codes from different tags is allowed (themes may span tags)."""
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "theme",
                    "name": "T1",
                    "tag": "Problem",
                    "status": "draft",
                },
                {
                    "id": 10,
                    "type": "code",
                    "name": "C1",
                    "tag": "Problem.Cause",
                    "status": "approved",
                },
                {
                    "id": 11,
                    "type": "code",
                    "name": "C2",
                    "tag": "Problem.Impact",
                    "status": "approved",
                },
            ],
            [(1, 10, "composed-of"), (1, 11, "composed-of")],
        )
        # Should not raise — themes may span multiple tags
        validate_constraint(
            {"id": 1, "type": "theme", "tag": "Problem"},
            "approve",
            graph=G,
            tag_dag=self.tag_dag,
        )

    def test_theme_with_three_codes_same_tag_approves(self):
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "theme",
                    "name": "T1",
                    "tag": "Problem",
                    "status": "draft",
                },
                {
                    "id": 10,
                    "type": "code",
                    "name": "C1",
                    "tag": "Problem",
                    "status": "approved",
                },
                {
                    "id": 11,
                    "type": "code",
                    "name": "C2",
                    "tag": "Problem",
                    "status": "approved",
                },
                {
                    "id": 12,
                    "type": "code",
                    "name": "C3",
                    "tag": "Problem",
                    "status": "approved",
                },
            ],
            [(1, 10, "composed-of"), (1, 11, "composed-of"), (1, 12, "composed-of")],
        )
        validate_constraint(
            {"id": 1, "type": "theme", "tag": "Problem"},
            "approve",
            graph=G,
            tag_dag=self.tag_dag,
        )


# ---------------------------------------------------------------------------
# Rule 3: theme -> one interpretation upon approval
# ---------------------------------------------------------------------------


class TestRule3ThemeOneInterpretation(unittest.TestCase):
    """Rule 3: theme must belong to at most one approved interpretation."""

    def setUp(self):
        self.tag_dag = _make_tag_dag()

    def test_theme_not_spanned_by_any_interpretation_approves(self):
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "theme",
                    "name": "T1",
                    "tag": "Problem",
                    "status": "draft",
                },
                {
                    "id": 10,
                    "type": "code",
                    "name": "C1",
                    "tag": "Problem",
                    "status": "approved",
                },
                {
                    "id": 11,
                    "type": "code",
                    "name": "C2",
                    "tag": "Problem",
                    "status": "approved",
                },
            ],
            [(1, 10, "composed-of"), (1, 11, "composed-of")],
        )
        validate_constraint(
            {"id": 1, "type": "theme", "tag": "Problem"},
            "approve",
            graph=G,
            tag_dag=self.tag_dag,
        )

    def test_theme_spanned_by_draft_interpretation_rejected(self):
        """Now rejects draft interpretations too (stricter enforcement)."""
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "theme",
                    "name": "T1",
                    "tag": "Problem",
                    "status": "draft",
                },
                {
                    "id": 10,
                    "type": "code",
                    "name": "C1",
                    "tag": "Problem",
                    "status": "approved",
                },
                {
                    "id": 11,
                    "type": "code",
                    "name": "C2",
                    "tag": "Problem",
                    "status": "approved",
                },
                {"id": 20, "type": "interpretation", "name": "I1", "status": "draft"},
            ],
            [(1, 10, "composed-of"), (1, 11, "composed-of"), (20, 1, "spans")],
        )
        with self.assertRaises(ConstraintError) as ctx:
            validate_constraint(
                {"id": 1, "type": "theme", "tag": "Problem"},
                "approve",
                graph=G,
                tag_dag=self.tag_dag,
            )
        self.assertIn("already spanned", str(ctx.exception))

    def test_theme_spanned_by_approved_interpretation_rejected(self):
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "theme",
                    "name": "T1",
                    "tag": "Problem",
                    "status": "draft",
                },
                {
                    "id": 10,
                    "type": "code",
                    "name": "C1",
                    "tag": "Problem",
                    "status": "approved",
                },
                {
                    "id": 11,
                    "type": "code",
                    "name": "C2",
                    "tag": "Problem",
                    "status": "approved",
                },
                {
                    "id": 20,
                    "type": "interpretation",
                    "name": "I1",
                    "status": "approved",
                },
            ],
            [(1, 10, "composed-of"), (1, 11, "composed-of"), (20, 1, "spans")],
        )
        with self.assertRaises(ConstraintError) as ctx:
            validate_constraint(
                {"id": 1, "type": "theme", "tag": "Problem"},
                "approve",
                graph=G,
                tag_dag=self.tag_dag,
            )
        self.assertEqual(ctx.exception.code, CONSTRAINT_THEME_MULTI_INTERP)


# ---------------------------------------------------------------------------
# Rule 4: interpretation tag_spans contiguous subtree
# ---------------------------------------------------------------------------


class TestRule4ContiguousSubtree(unittest.TestCase):
    """Rule 4: interpretation tag_spans must form a contiguous subtree."""

    def setUp(self):
        self.tag_dag = _make_tag_dag()

    def test_single_tag_contiguous(self):
        tag_dag = _make_chain_dag()
        validate_constraint(
            {"type": "interpretation", "tag_spans": {"A"}},
            "create",
            graph=nx.DiGraph(),
            tag_dag=tag_dag,
        )

    def test_parent_and_child_contiguous(self):
        validate_constraint(
            {"type": "interpretation", "tag_spans": {"Problem", "Problem.Cause"}},
            "create",
            graph=nx.DiGraph(),
            tag_dag=self.tag_dag,
        )

    def test_full_branch_contiguous(self):
        tag_dag = _make_chain_dag()
        validate_constraint(
            {"type": "interpretation", "tag_spans": {"A", "A.B", "A.B.C"}},
            "create",
            graph=nx.DiGraph(),
            tag_dag=tag_dag,
        )

    def test_siblings_under_same_parent_contiguous(self):
        validate_constraint(
            {
                "type": "interpretation",
                "tag_spans": {
                    "Problem.Cause",
                    "Problem.Solution",
                    "Problem.Impact",
                    "Problem",
                },
            },
            "create",
            graph=nx.DiGraph(),
            tag_dag=self.tag_dag,
        )

    def test_gap_missing_intermediate_rejected(self):
        tag_dag = _make_chain_dag()
        with self.assertRaises(ConstraintError) as ctx:
            validate_constraint(
                {"type": "interpretation", "tag_spans": {"A", "A.B.C"}},
                "create",
                graph=nx.DiGraph(),
                tag_dag=tag_dag,
            )
        self.assertEqual(
            ctx.exception.code,
            CONSTRAINT_NONCONTIGUOUS_SPAN,
        )
        self.assertIn("A.B", str(ctx.exception))

    def test_disjoint_roots_rejected(self):
        tag_dag = _make_disjoint_tag_dag()
        with self.assertRaises(ConstraintError):
            validate_constraint(
                {"type": "interpretation", "tag_spans": {"X.X1", "Y.Y1"}},
                "create",
                graph=nx.DiGraph(),
                tag_dag=tag_dag,
            )

    def test_empty_tag_spans_contiguous(self):
        validate_constraint(
            {"type": "interpretation", "tag_spans": set()},
            "create",
            graph=nx.DiGraph(),
            tag_dag=self.tag_dag,
        )

    def test_interpretation_approval_checks_contiguity(self):
        with self.assertRaises(ConstraintError) as ctx:
            tag_dag = _make_chain_dag()
            validate_constraint(
                {"type": "interpretation", "tag_spans": {"A", "A.B.C"}},
                "approve",
                graph=nx.DiGraph(),
                tag_dag=tag_dag,
            )
        self.assertEqual(
            ctx.exception.code,
            CONSTRAINT_NONCONTIGUOUS_SPAN,
        )

    def test_multi_level_gap_rejected(self):
        """A -> A.B -> A.B.C -> A.B.C.D, missing A.B and A.B.C."""
        G = nx.DiGraph()
        G.add_node("A", depth=0)
        G.add_node("A.B", depth=1)
        G.add_node("A.B.C", depth=2)
        G.add_node("A.B.C.D", depth=3)
        G.add_edge("A", "A.B")
        G.add_edge("A.B", "A.B.C")
        G.add_edge("A.B.C", "A.B.C.D")
        with self.assertRaises(ConstraintError):
            validate_constraint(
                {"type": "interpretation", "tag_spans": {"A", "A.B.C.D"}},
                "create",
                graph=nx.DiGraph(),
                tag_dag=G,
            )


# ---------------------------------------------------------------------------
# Rule 5: tag exists in ontology
# ---------------------------------------------------------------------------


class TestRule5TagExists(unittest.TestCase):
    """Rule 5: assigned tag must exist in the ontology DAG."""

    def setUp(self):
        self.tag_dag = _make_tag_dag()

    def test_existing_tag_assign_tag_ok(self):
        validate_constraint(
            {"tag": "Problem.Cause"},
            "assign_tag",
            graph=nx.DiGraph(),
            tag_dag=self.tag_dag,
        )

    def test_nonexistent_tag_assign_tag_rejected(self):
        with self.assertRaises(ConstraintError) as ctx:
            validate_constraint(
                {"tag": "Nonexistent.Tag"},
                "assign_tag",
                graph=nx.DiGraph(),
                tag_dag=self.tag_dag,
            )
        self.assertEqual(ctx.exception.code, CONSTRAINT_UNKNOWN_TAG)

    def test_existing_tag_on_code_approval_ok(self):
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "code",
                    "name": "C1",
                    "tag": "Problem.Cause",
                    "status": "draft",
                }
            ],
            [],
        )
        validate_constraint(
            {"id": 1, "type": "code", "tag": "Problem.Cause"},
            "approve",
            graph=G,
            tag_dag=self.tag_dag,
        )

    def test_nonexistent_tag_on_merge_rejected(self):
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "code",
                    "name": "C1",
                    "tag": "Bad.Tag",
                    "status": "draft",
                }
            ],
            [],
        )
        with self.assertRaises(ConstraintError):
            validate_constraint(
                {"id": 1, "type": "code", "tag": "Bad.Tag"},
                "merge",
                graph=G,
                tag_dag=self.tag_dag,
            )

    def test_interpretation_create_all_tags_exist_ok(self):
        validate_constraint(
            {
                "type": "interpretation",
                "tag_spans": {"Problem.Cause", "Problem.Solution", "Problem"},
            },
            "create",
            graph=nx.DiGraph(),
            tag_dag=self.tag_dag,
        )

    def test_interpretation_create_with_bad_tag_rejected(self):
        with self.assertRaises(ConstraintError) as ctx:
            validate_constraint(
                {"type": "interpretation", "tag_spans": {"Problem", "Nonexistent"}},
                "create",
                graph=nx.DiGraph(),
                tag_dag=self.tag_dag,
            )
        self.assertEqual(ctx.exception.code, CONSTRAINT_UNKNOWN_TAG)


# ---------------------------------------------------------------------------
# Rule 6: no cycles after merge
# ---------------------------------------------------------------------------


class TestRule6NoCycles(unittest.TestCase):
    """Rule 6: merge must not introduce cycles in the graph."""

    def setUp(self):
        self.tag_dag = _make_tag_dag()

    def test_acyclic_graph_merge_ok(self):
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "code",
                    "name": "C1",
                    "tag": "Problem",
                    "status": "draft",
                },
                {
                    "id": 2,
                    "type": "code",
                    "name": "C2",
                    "tag": "Problem",
                    "status": "draft",
                },
            ],
            [],
        )
        validate_constraint(
            {"id": 1, "type": "code", "tag": "Problem"},
            "merge",
            graph=G,
            tag_dag=self.tag_dag,
        )

    def test_cyclic_graph_merge_rejected(self):
        """Simple cycle: 1 -> 2 -> 1."""
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "code",
                    "name": "C1",
                    "tag": "Problem",
                    "status": "draft",
                },
                {
                    "id": 2,
                    "type": "code",
                    "name": "C2",
                    "tag": "Problem",
                    "status": "draft",
                },
            ],
            [(1, 2, "neighbor"), (2, 1, "neighbor")],
        )
        with self.assertRaises(ConstraintError) as ctx:
            validate_constraint(
                {"id": 1, "type": "code", "tag": "Problem"},
                "merge",
                graph=G,
                tag_dag=self.tag_dag,
            )
        self.assertEqual(ctx.exception.code, CONSTRAINT_CYCLE_AFTER_MERGE)

    def test_self_loop_rejected(self):
        """Self-loop on a single node."""
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "code",
                    "name": "C1",
                    "tag": "Problem",
                    "status": "draft",
                }
            ],
            [(1, 1, "neighbor")],
        )
        with self.assertRaises(ConstraintError):
            validate_constraint(
                {"id": 1, "type": "code", "tag": "Problem"},
                "merge",
                graph=G,
                tag_dag=self.tag_dag,
            )

    def test_three_node_cycle_rejected(self):
        """1 -> 2 -> 3 -> 1."""
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "code",
                    "name": "C1",
                    "tag": "Problem",
                    "status": "draft",
                },
                {
                    "id": 2,
                    "type": "code",
                    "name": "C2",
                    "tag": "Problem",
                    "status": "draft",
                },
                {
                    "id": 3,
                    "type": "code",
                    "name": "C3",
                    "tag": "Problem",
                    "status": "draft",
                },
            ],
            [(1, 2, "neighbor"), (2, 3, "neighbor"), (3, 1, "neighbor")],
        )
        with self.assertRaises(ConstraintError):
            validate_constraint(
                {"id": 1, "type": "code", "tag": "Problem"},
                "merge",
                graph=G,
                tag_dag=self.tag_dag,
            )

    def test_merge_with_tag_spans_contiguity_and_cycle_check(self):
        """Merge checks both Rule 4 (contiguity) and Rule 6 (cycles)."""
        tag_dag = _make_chain_dag()
        G = _make_graph_with_nodes(
            [
                {"id": 1, "type": "code", "name": "C1", "tag": "A", "status": "draft"},
                {"id": 2, "type": "code", "name": "C2", "tag": "A", "status": "draft"},
            ],
            [(1, 2, "neighbor"), (2, 1, "neighbor")],
        )
        with self.assertRaises(ConstraintError) as ctx:
            validate_constraint(
                {"id": 1, "type": "code", "tag": "A", "tag_spans": {"A", "A.B"}},
                "merge",
                graph=G,
                tag_dag=tag_dag,
            )
        # Cycle check fires before contiguity for merge
        self.assertEqual(ctx.exception.code, CONSTRAINT_CYCLE_AFTER_MERGE)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


class TestValidateConstraintDispatch(unittest.TestCase):
    """validate_constraint handles entity type / action dispatch correctly."""

    def setUp(self):
        self.tag_dag = _make_tag_dag()

    def test_unknown_action_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            validate_constraint(
                {"type": "code", "id": 1},
                "unknown_action",
                graph=nx.DiGraph(),
                tag_dag=self.tag_dag,
            )
        self.assertIn("unknown_action", str(ctx.exception))

    def test_approve_unknown_type_is_noop(self):
        """Unknown entity type with approve does not raise."""
        validate_constraint(
            {"type": "unknown"},
            "approve",
            graph=nx.DiGraph(),
            tag_dag=self.tag_dag,
        )

    def test_assign_tag_without_tag_is_noop(self):
        validate_constraint(
            {},
            "assign_tag",
            graph=nx.DiGraph(),
            tag_dag=self.tag_dag,
        )

    def test_merge_without_tag_or_tag_spans_still_checks_cycle(self):
        G = _make_graph_with_nodes(
            [
                {
                    "id": 1,
                    "type": "code",
                    "name": "C1",
                    "tag": "Problem",
                    "status": "draft",
                }
            ],
            [(1, 1, "neighbor")],
        )
        with self.assertRaises(ConstraintError):
            validate_constraint(
                {"id": 1, "type": "code"},
                "merge",
                graph=G,
                tag_dag=self.tag_dag,
            )


# ---------------------------------------------------------------------------
# is_contiguous_subtree (shared with Feature 50)
# ---------------------------------------------------------------------------


class TestIsContiguousSubtree(unittest.TestCase):
    """is_contiguous_subtree as a pure boolean check."""

    def test_empty_set_trivially_contiguous(self):
        self.assertTrue(is_contiguous_subtree(set(), _make_chain_dag()))

    def test_single_tag_trivially_contiguous(self):
        self.assertTrue(is_contiguous_subtree({"A"}, _make_chain_dag()))

    def test_parent_and_child_contiguous(self):
        self.assertTrue(
            is_contiguous_subtree({"A", "A.B"}, _make_chain_dag()),
        )

    def test_gap_not_contiguous(self):
        self.assertFalse(
            is_contiguous_subtree({"A", "A.B.C"}, _make_chain_dag()),
        )

    def test_full_chain_contiguous(self):
        self.assertTrue(
            is_contiguous_subtree(
                {"A", "A.B", "A.B.C"},
                _make_chain_dag(),
            ),
        )

    def test_standard_tree_siblings_contiguous(self):
        tag_dag = _make_tag_dag()
        self.assertTrue(
            is_contiguous_subtree(
                {"Problem", "Problem.Cause", "Problem.Solution", "Problem.Impact"},
                tag_dag,
            ),
        )

    def test_disjoint_roots_not_contiguous(self):
        self.assertFalse(
            is_contiguous_subtree({"X.X1", "Y.Y1"}, _make_disjoint_tag_dag()),
        )

    def test_grandchild_without_parent_not_contiguous(self):
        # Single tag is trivially contiguous
        self.assertTrue(
            is_contiguous_subtree({"A.B.C"}, _make_chain_dag()),
        )
        # With intermediate missing: A and A.B.C without A.B
        self.assertFalse(
            is_contiguous_subtree({"A", "A.B.C"}, _make_chain_dag()),
        )

    def test_unknown_tag_raises(self):
        import networkx as nx

        tag_dag = _make_chain_dag()
        with self.assertRaises(nx.NetworkXError):
            is_contiguous_subtree({"A", "Unknown"}, tag_dag)

    # ── Feature 50 acceptance-criteria examples ──────────────────────

    def test_ac_example_problem_contiguous(self):
        """AC: {Problem, Problem.Cause, Problem.Impact} → contiguous."""
        tag_dag = _make_tag_dag()
        self.assertTrue(
            is_contiguous_subtree(
                {"Problem", "Problem.Cause", "Problem.Impact"}, tag_dag
            ),
        )

    def test_ac_example_siblings_no_parent(self):
        """AC: {Problem.Cause, Problem.Impact} → contiguous (downward-closed policy).

        Sibling leaf tags without their shared parent are contiguous
        because no intermediate nodes exist on paths from LCA to each tag.
        """
        tag_dag = _make_tag_dag()
        self.assertTrue(
            is_contiguous_subtree({"Problem.Cause", "Problem.Impact"}, tag_dag),
        )

    def test_ac_example_noncontiguous_gap(self):
        """AC: {Problem, Problem.Impact.Scope} → non-contiguous (gap).

        Missing Problem.Impact on path between Problem and
        Problem.Impact.Scope.
        """
        tag_dag = _make_tag_dag()
        self.assertFalse(
            is_contiguous_subtree({"Problem", "Problem.Impact.Scope"}, tag_dag),
        )


# ---------------------------------------------------------------------------
# _missing_intermediates (helper for error messages)
# ---------------------------------------------------------------------------


class TestMissingIntermediates(unittest.TestCase):
    """_missing_intermediates returns gap tags for non-contiguous sets."""

    def test_empty_set_returns_empty(self):
        self.assertEqual(_missing_intermediates(set(), _make_chain_dag()), set())

    def test_single_tag_returns_empty(self):
        self.assertEqual(_missing_intermediates({"A"}, _make_chain_dag()), set())

    def test_contiguous_set_returns_empty(self):
        self.assertEqual(
            _missing_intermediates({"A", "A.B"}, _make_chain_dag()),
            set(),
        )

    def test_non_contiguous_returns_gap(self):
        self.assertEqual(
            _missing_intermediates({"A", "A.B.C"}, _make_chain_dag()),
            {"A.B"},
        )

    def test_disjoint_roots_returns_empty(self):
        """Disjoint tags have no common ancestor—helper returns empty set."""
        self.assertEqual(
            _missing_intermediates({"X.X1", "Y.Y1"}, _make_disjoint_tag_dag()),
            set(),
        )


if __name__ == "__main__":
    unittest.main()
