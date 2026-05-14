"""Unit tests for inference/interpretation_span_grouping.py — pure DAG functions."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src" / "python"))

import networkx as nx
from inference.interpretation_span_grouping import (
    build_ontology_subtree,
    build_tag_hierarchy,
    group_ready_tags_into_spans,
)


def _make_tree_dag() -> nx.DiGraph:
    """Build a simple tree DAG: A -> {A.B, A.C}, A.B -> {A.B.D}."""
    dag = nx.DiGraph()
    dag.add_node("A", depth=0)
    dag.add_node("A.B", depth=1)
    dag.add_node("A.C", depth=1)
    dag.add_node("A.B.D", depth=2)
    dag.add_edge("A", "A.B")
    dag.add_edge("A", "A.C")
    dag.add_edge("A.B", "A.B.D")
    return dag


class TestGroupReadyTagsIntoSpans(unittest.TestCase):
    """group_ready_tags_into_spans: partition ready tags into contiguous spans."""

    def setUp(self):
        self.dag = _make_tree_dag()

    def test_empty_ready_tags(self):
        spans = group_ready_tags_into_spans(set(), self.dag)
        self.assertEqual(spans, [])

    def test_single_tag_returns_empty(self):
        spans = group_ready_tags_into_spans({"A"}, self.dag)
        self.assertEqual(spans, [])

    def test_parent_with_two_children_forms_one_span(self):
        spans = group_ready_tags_into_spans({"A", "A.B", "A.C"}, self.dag)
        self.assertEqual(len(spans), 1)
        self.assertSetEqual(spans[0], {"A", "A.B", "A.C"})

    def test_parent_and_child_forms_one_span(self):
        spans = group_ready_tags_into_spans({"A", "A.B"}, self.dag)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0], {"A", "A.B"})

    def test_full_subtree_forms_one_span(self):
        spans = group_ready_tags_into_spans({"A", "A.B", "A.C", "A.B.D"}, self.dag)
        self.assertEqual(len(spans), 1)
        self.assertSetEqual(spans[0], {"A", "A.B", "A.C", "A.B.D"})

    def test_two_separate_branches(self):
        dag = nx.DiGraph()
        dag.add_node("X", depth=0)
        dag.add_node("X.A", depth=1)
        dag.add_node("X.B", depth=1)
        dag.add_node("Y", depth=0)
        dag.add_node("Y.A", depth=1)
        dag.add_edge("X", "X.A")
        dag.add_edge("X", "X.B")
        dag.add_edge("Y", "Y.A")
        spans = group_ready_tags_into_spans({"X", "X.A", "X.B", "Y", "Y.A"}, dag)
        self.assertEqual(len(spans), 2)
        for s in spans:
            self.assertGreaterEqual(len(s), 2)


class TestBuildTagHierarchy(unittest.TestCase):
    """build_tag_hierarchy: ancestor chains for prompt context."""

    def setUp(self):
        self.dag = _make_tree_dag()

    def test_single_tag_hierarchy(self):
        hierarchy = build_tag_hierarchy({"A.B"}, self.dag)
        self.assertEqual(hierarchy, [["A", "A.B"]])

    def test_multi_tag_hierarchy(self):
        hierarchy = build_tag_hierarchy({"A.B", "A.C"}, self.dag)
        self.assertEqual(len(hierarchy), 2)
        self.assertIn(["A", "A.B"], hierarchy)
        self.assertIn(["A", "A.C"], hierarchy)

    def test_root_tag_hierarchy(self):
        hierarchy = build_tag_hierarchy({"A"}, self.dag)
        self.assertEqual(hierarchy, [["A"]])


class TestBuildOntologySubtree(unittest.TestCase):
    """build_ontology_subtree: indented tree diagram for prompt."""

    def setUp(self):
        self.dag = _make_tree_dag()

    def test_single_tag(self):
        result = build_ontology_subtree({"A"}, self.dag)
        self.assertEqual(result, "A")

    def test_parent_and_child(self):
        result = build_ontology_subtree({"A", "A.B"}, self.dag)
        lines = result.split("\n")
        self.assertEqual(lines[0], "A")
        self.assertEqual(lines[1], "  A.B")

    def test_full_subtree(self):
        result = build_ontology_subtree({"A", "A.B", "A.C", "A.B.D"}, self.dag)
        lines = result.split("\n")
        self.assertIn("A", lines)
        self.assertIn("  A.B", lines)
        self.assertIn("  A.C", lines)
        self.assertIn("    A.B.D", lines)

    def test_two_roots(self):
        dag = nx.DiGraph()
        dag.add_node("X")
        dag.add_node("Y")
        dag.add_edge("Y", "Y.Z")
        result = build_ontology_subtree({"X", "Y", "Y.Z"}, dag)
        self.assertIn("X", result)
        self.assertIn("Y", result)
        self.assertIn("  Y.Z", result)

    def test_empty_tags_returns_empty(self):
        result = build_ontology_subtree(set(), self.dag)
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
