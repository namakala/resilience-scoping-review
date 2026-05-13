"""Unit tests for ontology traversal operations.

Test coverage:
- get_ancestors: deep tag, root tag, ordering (root -> parent)
- get_descendants: root, leaf, intermediate, depth ordering
- get_subtree: includes self, superset of descendants
- is_ancestor: true, false, same tag
- Unknown tags raise KeyError for all 4 public functions
- Cache management: clear_traversal_cache forces recompute
- Performance: get_descendants on root with 1000 tags <50ms (cached)
"""

# flake8: noqa: E402
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import networkx as nx
import polars as pl


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


# Standard test tree (single-root):
#
#     Problem            depth 0
#     +-- Problem.Cause  depth 1
#     |   +-- Problem.Cause.Scope   depth 2
#     +-- Problem.Solution          depth 1
#     +-- Problem.Impact            depth 1
#         +-- Problem.Impact.Scope  depth 2


def _standard_tree():
    return [
        {
            "tag": "Problem",
            "parent": "",
            "description": "Root problem",
            "n_contents": 10,
        },
        {
            "tag": "Problem.Cause",
            "parent": "Problem",
            "description": "Causal factors",
            "n_contents": 4,
        },
        {
            "tag": "Problem.Cause.Scope",
            "parent": "Problem.Cause",
            "description": "Scope of cause",
            "n_contents": 2,
        },
        {
            "tag": "Problem.Solution",
            "parent": "Problem",
            "description": "Potential solutions",
            "n_contents": 3,
        },
        {
            "tag": "Problem.Impact",
            "parent": "Problem",
            "description": "Impact assessment",
            "n_contents": 3,
        },
        {
            "tag": "Problem.Impact.Scope",
            "parent": "Problem.Impact",
            "description": "Scope of impact",
            "n_contents": 1,
        },
    ]


def _non_overlapping_tree():
    """Two disjoint subtrees to test ancestor ordering."""
    return [
        {"tag": "A", "parent": "", "description": "Root A", "n_contents": 0},
        {"tag": "A.B", "parent": "A", "description": "Child", "n_contents": 0},
        {"tag": "A.B.C", "parent": "A.B", "description": "Grandchild", "n_contents": 0},
    ]


class TestOntologyTraversal(unittest.TestCase):
    """Test suite for ontology traversal functions."""

    def setUp(self):
        import ontology.dag as dag_mod
        import ontology.traversal as trav_mod

        dag_mod._ONTOLOGY_GRAPH = None
        trav_mod.clear_traversal_cache()

    # --- get_ancestors ---

    @patch("ontology.dag.load_tags")
    def test_get_ancestors_deep_tag(self, mock_load_tags):
        """Deep tag returns all ancestors ordered root -> parent."""
        mock_load_tags.return_value = _make_tags_lf(_standard_tree())
        from ontology.traversal import get_ancestors

        result = get_ancestors("Problem.Cause.Scope")
        self.assertEqual(result, ["Problem", "Problem.Cause"])

    @patch("ontology.dag.load_tags")
    def test_get_ancestors_root(self, mock_load_tags):
        """Root tag returns empty list."""
        mock_load_tags.return_value = _make_tags_lf(_standard_tree())
        from ontology.traversal import get_ancestors

        result = get_ancestors("Problem")
        self.assertEqual(result, [])

    @patch("ontology.dag.load_tags")
    def test_get_ancestors_ordering(self, mock_load_tags):
        """Ancestors ordered by depth ascending (root first)."""
        mock_load_tags.return_value = _make_tags_lf(_non_overlapping_tree())
        from ontology.traversal import get_ancestors

        result = get_ancestors("A.B.C")
        self.assertEqual(result, ["A", "A.B"])

    @patch("ontology.dag.load_tags")
    def test_get_ancestors_excludes_self(self, mock_load_tags):
        """Input tag is not included in ancestor list."""
        mock_load_tags.return_value = _make_tags_lf(_standard_tree())
        from ontology.traversal import get_ancestors

        result = get_ancestors("Problem.Cause.Scope")
        self.assertNotIn("Problem.Cause.Scope", result)

    # --- get_descendants ---

    @patch("ontology.dag.load_tags")
    def test_get_descendants_root(self, mock_load_tags):
        """Root returns all descendants sorted by depth."""
        mock_load_tags.return_value = _make_tags_lf(_standard_tree())
        from ontology.traversal import get_descendants

        result = get_descendants("Problem")
        # 5 descendants (all except root)
        self.assertEqual(len(result), 5)
        # Depth-1 tags come before depth-2 tags
        depths = []
        G = nx.DiGraph()
        for row in _standard_tree():
            G.add_node(row["tag"], depth=0)
        for row in _standard_tree():
            if row["parent"]:
                G.add_edge(row["parent"], row["tag"])
        from ontology.dag import _compute_graph_depths

        depths_map = _compute_graph_depths(G)
        for tag in result:
            depths.append(depths_map[tag])
        self.assertEqual(depths, sorted(depths))

    @patch("ontology.dag.load_tags")
    def test_get_descendants_leaf(self, mock_load_tags):
        """Leaf tag returns empty list."""
        mock_load_tags.return_value = _make_tags_lf(_standard_tree())
        from ontology.traversal import get_descendants

        result = get_descendants("Problem.Cause.Scope")
        self.assertEqual(result, [])

    @patch("ontology.dag.load_tags")
    def test_get_descendants_intermediate(self, mock_load_tags):
        """Intermediate tag returns its subtree only."""
        mock_load_tags.return_value = _make_tags_lf(_standard_tree())
        from ontology.traversal import get_descendants

        result = get_descendants("Problem.Cause")
        self.assertEqual(set(result), {"Problem.Cause.Scope"})

    @patch("ontology.dag.load_tags")
    def test_get_descendants_excludes_self(self, mock_load_tags):
        """Input tag is not included in descendants list."""
        mock_load_tags.return_value = _make_tags_lf(_standard_tree())
        from ontology.traversal import get_descendants

        result = get_descendants("Problem")
        self.assertNotIn("Problem", result)

    # --- get_subtree ---

    @patch("ontology.dag.load_tags")
    def test_get_subtree_includes_self(self, mock_load_tags):
        """Subtree includes the input tag itself."""
        mock_load_tags.return_value = _make_tags_lf(_standard_tree())
        from ontology.traversal import get_subtree

        result = get_subtree("Problem")
        self.assertIn("Problem", result)

    @patch("ontology.dag.load_tags")
    def test_get_subtree_superset_of_descendants(self, mock_load_tags):
        """Subtree = {tag} + descendants."""
        mock_load_tags.return_value = _make_tags_lf(_standard_tree())
        from ontology.traversal import get_descendants, get_subtree

        subtree = get_subtree("Problem.Cause")
        descendants = set(get_descendants("Problem.Cause"))
        self.assertEqual(subtree, {"Problem.Cause"} | descendants)

    @patch("ontology.dag.load_tags")
    def test_get_subtree_leaf(self, mock_load_tags):
        """Leaf subtree contains only the leaf itself."""
        mock_load_tags.return_value = _make_tags_lf(_standard_tree())
        from ontology.traversal import get_subtree

        result = get_subtree("Problem.Cause.Scope")
        self.assertEqual(result, {"Problem.Cause.Scope"})

    # --- is_ancestor ---

    @patch("ontology.dag.load_tags")
    def test_is_ancestor_true(self, mock_load_tags):
        """Direct and transitive ancestor relationships return True."""
        mock_load_tags.return_value = _make_tags_lf(_standard_tree())
        from ontology.traversal import is_ancestor

        self.assertTrue(is_ancestor("Problem", "Problem.Cause.Scope"))
        self.assertTrue(is_ancestor("Problem", "Problem.Cause"))
        self.assertTrue(is_ancestor("Problem.Cause", "Problem.Cause.Scope"))

    @patch("ontology.dag.load_tags")
    def test_is_ancestor_false(self, mock_load_tags):
        """Siblings and unrelated tags return False."""
        mock_load_tags.return_value = _make_tags_lf(_standard_tree())
        from ontology.traversal import is_ancestor

        # Sibling (different branches)
        self.assertFalse(is_ancestor("Problem.Cause", "Problem.Impact"))
        # Reverse direction
        self.assertFalse(is_ancestor("Problem.Cause.Scope", "Problem.Cause"))
        # Unrelated
        self.assertFalse(is_ancestor("Problem.Impact.Scope", "Problem.Cause"))

    @patch("ontology.dag.load_tags")
    def test_is_ancestor_same_tag(self, mock_load_tags):
        """Same tag returns False (a tag is not an ancestor of itself)."""
        mock_load_tags.return_value = _make_tags_lf(_standard_tree())
        from ontology.traversal import is_ancestor

        self.assertFalse(is_ancestor("Problem", "Problem"))

    # --- unknown tags ---

    @patch("ontology.dag.load_tags")
    def test_unknown_tag_raises_key_error(self, mock_load_tags):
        """All four public functions raise KeyError for unknown tags."""
        mock_load_tags.return_value = _make_tags_lf(_standard_tree())
        from ontology.traversal import (
            get_ancestors,
            get_descendants,
            get_subtree,
            is_ancestor,
        )

        with self.assertRaises(KeyError):
            get_ancestors("Nonexistent.Tag")
        with self.assertRaises(KeyError):
            get_descendants("Nonexistent.Tag")
        with self.assertRaises(KeyError):
            get_subtree("Nonexistent.Tag")
        with self.assertRaises(KeyError):
            is_ancestor("Nonexistent.Tag", "Problem")
        with self.assertRaises(KeyError):
            is_ancestor("Problem", "Nonexistent.Tag")

    # --- cache management ---

    @patch("ontology.dag.load_tags")
    def test_clear_cache_forces_recompute(self, mock_load_tags):
        """After clearing cache, fresh data is loaded on next call."""
        mock_load_tags.return_value = _make_tags_lf(_standard_tree())
        from ontology.dag import rebuild_tag_dag
        from ontology.traversal import clear_traversal_cache, get_descendants

        _ = get_descendants("Problem")
        mock_load_tags.return_value = _make_tags_lf(
            [
                {"tag": "Root", "parent": "", "description": "r", "n_contents": 1},
            ]
        )
        rebuild_tag_dag()
        clear_traversal_cache()
        result = get_descendants("Root")
        self.assertEqual(result, [])

    # --- performance ---

    @patch("ontology.dag.load_tags")
    def test_get_descendants_performance(self, mock_load_tags):
        """Cached get_descendants on root with 1000 tags <50ms."""
        n_tags = 1000
        tag_data = [
            {
                "tag": f"T{i}",
                "parent": f"T{i // 2}" if i > 0 else "",
                "description": f"Tag {i}",
                "n_contents": 0,
            }
            for i in range(n_tags)
        ]
        mock_load_tags.return_value = _make_tags_lf(tag_data)
        from ontology.traversal import get_descendants

        # First call warms cache
        get_descendants("T0")

        # Timed second call uses cache
        start = time.perf_counter()
        result = get_descendants("T0")
        elapsed = time.perf_counter() - start

        self.assertEqual(len(result), n_tags - 1)
        self.assertLess(
            elapsed,
            0.05,
            f"get_descendants took {elapsed * 1000:.2f}ms, expected <50ms",
        )


if __name__ == "__main__":
    unittest.main()
