"""Unit tests for tag DAG construction.

Test coverage:
- Node count, edge count for valid trees and forests
- Node attributes (tag_str, description, n_contents, depth)
- Depth computation (root=0, incremental +1 per level)
- Acyclicity validation (valid DAG, cycles, self-loops)
- Topological sort succeeds on valid DAG
- Missing parent auto-inferred as empty placeholder node
- Singleton caching (get_tag_dag, rebuild_tag_dag)
- Empty tags returns empty graph
"""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Add src/python to sys.path for imports
sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import networkx as nx
import polars as pl
from graph.exceptions import CycleError, ForeignKeyError


def _make_tags_lf(tag_data):
    """Convert list of dicts to a Polars LazyFrame matching load_tags schema."""
    df = pl.DataFrame(
        tag_data,
        schema={
            "tag": pl.String,
            "parent": pl.String,
            "description": pl.String,
            "n_contents": pl.Int64,
            "depth": pl.Int64,
        },
        orient="row",
    )
    return df.lazy()


# Tracked singleton state for rebuild tests
_REBUILD_COUNTER = 0


class TestTagDAG(unittest.TestCase):
    """Test suite for ontology tag DAG construction."""

    def setUp(self):
        # Reset singleton and build counter before each test
        import ontology.dag as dag_mod

        dag_mod._ONTOLOGY_GRAPH = None

        global _REBUILD_COUNTER
        _REBUILD_COUNTER = 0

    @patch("ontology.dag.load_tags")
    def test_build_tag_dag_node_count(self, mock_load_tags):
        """DAG node count equals number of tags."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "Root", "parent": "", "description": "Root", "n_contents": 5},
                {
                    "tag": "A",
                    "parent": "Root",
                    "description": "Child A",
                    "n_contents": 3,
                },
                {
                    "tag": "B",
                    "parent": "Root",
                    "description": "Child B",
                    "n_contents": 2,
                },
            ]
        )
        from ontology.dag import build_tag_dag

        G = build_tag_dag()
        self.assertEqual(G.number_of_nodes(), 3)

    @patch("ontology.dag.load_tags")
    def test_build_tag_dag_edge_count(self, mock_load_tags):
        """Simple parent-child produces one edge."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "Root", "parent": "", "description": "Root", "n_contents": 5},
                {"tag": "A", "parent": "Root", "description": "Child", "n_contents": 3},
            ]
        )
        from ontology.dag import build_tag_dag

        G = build_tag_dag()
        self.assertEqual(G.number_of_edges(), 1)

    @patch("ontology.dag.load_tags")
    def test_build_tag_dag_multiple_roots(self, mock_load_tags):
        """Forest with two disjoint trees builds correctly."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "Root1", "parent": "", "description": "First", "n_contents": 5},
                {
                    "tag": "Root2",
                    "parent": "",
                    "description": "Second",
                    "n_contents": 3,
                },
            ]
        )
        from ontology.dag import build_tag_dag

        G = build_tag_dag()
        self.assertEqual(G.number_of_nodes(), 2)
        self.assertEqual(G.number_of_edges(), 0)

    @patch("ontology.dag.load_tags")
    def test_build_tag_dag_deep_hierarchy(self, mock_load_tags):
        """Deeply nested tags have correct edge chain."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "A", "parent": "", "description": "d0", "n_contents": 0},
                {"tag": "A.B", "parent": "A", "description": "d1", "n_contents": 0},
                {"tag": "A.B.C", "parent": "A.B", "description": "d2", "n_contents": 0},
                {
                    "tag": "A.B.C.D",
                    "parent": "A.B.C",
                    "description": "d3",
                    "n_contents": 0,
                },
            ]
        )
        from ontology.dag import build_tag_dag

        G = build_tag_dag()
        self.assertEqual(G.number_of_edges(), 3)
        self.assertTrue(G.has_edge("A", "A.B"))
        self.assertTrue(G.has_edge("A.B", "A.B.C"))
        self.assertTrue(G.has_edge("A.B.C", "A.B.C.D"))

    @patch("ontology.dag.load_tags")
    def test_node_attributes(self, mock_load_tags):
        """Each node has tag_str, description, n_contents, depth."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "Root", "parent": "", "description": "desc", "n_contents": 7},
            ]
        )
        from ontology.dag import build_tag_dag

        G = build_tag_dag()
        attrs = G.nodes["Root"]
        self.assertEqual(attrs["tag_str"], "Root")
        self.assertEqual(attrs["description"], "desc")
        self.assertEqual(attrs["n_contents"], 7)
        self.assertIn("depth", attrs)

    @patch("ontology.dag.load_tags")
    def test_depth_root_is_zero(self, mock_load_tags):
        """Root tag has depth 0."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "Root", "parent": "", "description": "r", "n_contents": 1},
            ]
        )
        from ontology.dag import build_tag_dag

        G = build_tag_dag()
        self.assertEqual(G.nodes["Root"]["depth"], 0)

    @patch("ontology.dag.load_tags")
    def test_depth_nested_tags(self, mock_load_tags):
        """Nested tags have incremental depth."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "A", "parent": "", "description": "d0", "n_contents": 0},
                {"tag": "A.B", "parent": "A", "description": "d1", "n_contents": 0},
                {"tag": "A.B.C", "parent": "A.B", "description": "d2", "n_contents": 0},
            ]
        )
        from ontology.dag import build_tag_dag

        G = build_tag_dag()
        self.assertEqual(G.nodes["A"]["depth"], 0)
        self.assertEqual(G.nodes["A.B"]["depth"], 1)
        self.assertEqual(G.nodes["A.B.C"]["depth"], 2)

    @patch("ontology.dag.load_tags")
    def test_depth_multiple_roots(self, mock_load_tags):
        """Both roots have depth 0 in a forest."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "R1", "parent": "", "description": "f", "n_contents": 1},
                {"tag": "R2", "parent": "", "description": "s", "n_contents": 2},
            ]
        )
        from ontology.dag import build_tag_dag

        G = build_tag_dag()
        self.assertEqual(G.nodes["R1"]["depth"], 0)
        self.assertEqual(G.nodes["R2"]["depth"], 0)

    @patch("ontology.dag.load_tags")
    def test_validate_tag_dag_valid(self, mock_load_tags):
        """Valid DAG does not raise."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "A", "parent": "", "description": "r", "n_contents": 0},
                {"tag": "A.B", "parent": "A", "description": "c", "n_contents": 0},
            ]
        )
        from ontology.dag import build_tag_dag, validate_tag_dag

        G = build_tag_dag()
        validate_tag_dag(G)

    @patch("ontology.dag.load_tags")
    def test_validate_tag_dag_cycle_raises_error(self, mock_load_tags):
        """Cycle between three nodes raises CycleError with cycle path."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "A", "parent": "", "description": "n1", "n_contents": 0},
                {"tag": "B", "parent": "A", "description": "n2", "n_contents": 0},
                {"tag": "C", "parent": "B", "description": "n3", "n_contents": 0},
            ]
        )
        from ontology.dag import build_tag_dag

        G = build_tag_dag()
        # Manually add back-edge to create a cycle
        G.add_edge("C", "A")

        from ontology.dag import validate_tag_dag

        with self.assertRaises(CycleError) as ctx:
            validate_tag_dag(G)
        self.assertIn("Cycle detected", str(ctx.exception))

    @patch("ontology.dag.load_tags")
    def test_validate_tag_dag_self_loop(self, mock_load_tags):
        """Self-loop raises CycleError."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "A", "parent": "", "description": "n1", "n_contents": 0},
            ]
        )
        from ontology.dag import build_tag_dag

        G = build_tag_dag()
        G.add_edge("A", "A")

        from ontology.dag import validate_tag_dag

        with self.assertRaises(CycleError):
            validate_tag_dag(G)

    @patch("ontology.dag.load_tags")
    def test_topological_sort_succeeds(self, mock_load_tags):
        """Topological sort returns a valid ordering."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "A", "parent": "", "description": "r", "n_contents": 0},
                {"tag": "A.B", "parent": "A", "description": "c", "n_contents": 0},
                {"tag": "A.B.C", "parent": "A.B", "description": "d", "n_contents": 0},
            ]
        )
        from ontology.dag import build_tag_dag

        G = build_tag_dag()
        ordering = list(nx.topological_sort(G))
        self.assertEqual(len(ordering), 3)
        # Verify A comes before A.B, A.B comes before A.B.C
        a_idx = ordering.index("A")
        ab_idx = ordering.index("A.B")
        abc_idx = ordering.index("A.B.C")
        self.assertLess(a_idx, ab_idx)
        self.assertLess(ab_idx, abc_idx)

    @patch("ontology.dag.load_tags")
    def test_get_tag_dag_caching(self, mock_load_tags):
        """Two calls to get_tag_dag return the same singleton."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "X", "parent": "", "description": "x", "n_contents": 1},
            ]
        )
        from ontology.dag import get_tag_dag

        first = get_tag_dag()
        second = get_tag_dag()
        self.assertIs(first, second)

    @patch("ontology.dag.load_tags")
    def test_rebuild_tag_dag_replaces_cache(self, mock_load_tags):
        """rebuild_tag_dag creates a new singleton object."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "X", "parent": "", "description": "x", "n_contents": 1},
            ]
        )
        from ontology.dag import get_tag_dag, rebuild_tag_dag

        first = get_tag_dag()
        second = rebuild_tag_dag()
        self.assertIsNot(first, second)
        self.assertIs(second, get_tag_dag())

    @patch("ontology.dag.load_tags")
    def test_missing_parent_inferred(self, mock_load_tags):
        """Missing parent auto-inferred as empty placeholder with correct edges."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "A.B", "parent": "A", "description": "orphan", "n_contents": 1},
            ]
        )
        from ontology.dag import build_tag_dag

        G = build_tag_dag()
        # Missing parent A was inferred
        self.assertIn("A", G.nodes)
        self.assertEqual(G.nodes["A"]["description"], "")
        self.assertEqual(G.nodes["A"]["n_contents"], 0)
        self.assertEqual(G.nodes["A"]["tag_str"], "A")
        # Edge A -> A.B exists
        self.assertTrue(G.has_edge("A", "A.B"))
        # Original node preserved
        self.assertEqual(G.nodes["A.B"]["description"], "orphan")
        self.assertEqual(G.nodes["A.B"]["n_contents"], 1)
        self.assertEqual(G.number_of_nodes(), 2)
        self.assertEqual(G.number_of_edges(), 1)

    @patch("ontology.dag.load_tags")
    def test_empty_tags_returns_empty_graph(self, mock_load_tags):
        """No tags produces an empty DiGraph."""
        mock_load_tags.return_value = _make_tags_lf([])
        from ontology.dag import build_tag_dag

        G = build_tag_dag()
        self.assertEqual(G.number_of_nodes(), 0)
        self.assertEqual(G.number_of_edges(), 0)

    @patch("ontology.dag.load_tags")
    def test_n_contents_preserved(self, mock_load_tags):
        """n_contents stored as node attribute matches input."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "R", "parent": "", "description": "root", "n_contents": 42},
                {"tag": "R.C", "parent": "R", "description": "child", "n_contents": 7},
            ]
        )
        from ontology.dag import build_tag_dag

        G = build_tag_dag()
        self.assertEqual(G.nodes["R"]["n_contents"], 42)
        self.assertEqual(G.nodes["R.C"]["n_contents"], 7)

    @patch("ontology.dag.load_tags")
    def test_multiple_missing_parents_inferred(self, mock_load_tags):
        """Multiple missing parents auto-inferred with correct chain wiring."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "X.Y", "parent": "X", "description": "a", "n_contents": 0},
                {"tag": "X.Y.Z", "parent": "X.Y", "description": "b", "n_contents": 0},
                {"tag": "P.Q", "parent": "P", "description": "c", "n_contents": 0},
            ]
        )
        from ontology.dag import build_tag_dag

        G = build_tag_dag()
        # Both P and X inferred as placeholders
        self.assertIn("P", G.nodes)
        self.assertIn("X", G.nodes)
        self.assertEqual(G.nodes["P"]["description"], "")
        self.assertEqual(G.nodes["X"]["description"], "")
        self.assertEqual(G.nodes["P"]["n_contents"], 0)
        self.assertEqual(G.nodes["X"]["n_contents"], 0)
        # Edge from inferred P to P.Q
        self.assertTrue(G.has_edge("P", "P.Q"))
        # Edge from inferred X to X.Y
        self.assertTrue(G.has_edge("X", "X.Y"))
        # Edge X.Y -> X.Y.Z (X.Y is existing original node)
        self.assertTrue(G.has_edge("X.Y", "X.Y.Z"))
        # Total: 3 original + 2 inferred = 5 nodes
        self.assertEqual(G.number_of_nodes(), 5)
        self.assertEqual(G.number_of_edges(), 3)

    @patch("ontology.dag.load_tags")
    def test_build_tag_dag_rejects_cycle_during_build(self, mock_load_tags):
        """build_tag_dag raises CycleError if tags create a cycle via parent refs."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "A", "parent": "C", "description": "n1", "n_contents": 0},
                {"tag": "B", "parent": "A", "description": "n2", "n_contents": 0},
                {"tag": "C", "parent": "B", "description": "n3", "n_contents": 0},
            ]
        )
        from ontology.dag import build_tag_dag

        with self.assertRaises(CycleError):
            build_tag_dag()

    @patch("ontology.dag.load_tags")
    def test_validate_tag_dag_defaults_to_cache(self, mock_load_tags):
        """validate_tag_dag with no arg uses cached DAG."""
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "A", "parent": "", "description": "r", "n_contents": 0},
            ]
        )
        from ontology.dag import get_tag_dag, validate_tag_dag

        get_tag_dag()
        validate_tag_dag()

    @patch("ontology.dag.load_tags")
    def test_validate_tag_dag_on_empty_graph(self, mock_load_tags):
        """Empty graph passes validation."""
        mock_load_tags.return_value = _make_tags_lf([])
        from ontology.dag import build_tag_dag, validate_tag_dag

        G = build_tag_dag()
        validate_tag_dag(G)


if __name__ == "__main__":
    unittest.main()
