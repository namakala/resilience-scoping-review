"""Unit tests for scope restriction helper (Feature 22).

Test coverage:
- Leaf tag returns set containing only itself
- Root tag returns all tags in ontology
- Intermediate tag returns itself + descendants
- Unknown tag raises KeyError
- Cache hit returns result from DuckDB without recompute
- Cache miss recomputes and persists to DuckDB
- Cache stale recomputes and clears stale flag
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


def _make_exemplars_lf(exemplar_data):
    """Convert list of dicts to a Polars LazyFrame matching load_exemplars schema."""
    df = pl.DataFrame(
        exemplar_data,
        schema={
            "id": pl.Int64,
            "document": pl.String,
            "tag": pl.String,
            "content": pl.String,
            "keywords": pl.List(pl.String),
            "content_hash": pl.String,
            "keyword_count": pl.Int64,
        },
        orient="row",
    )
    return df.lazy()


# Standard test tree (same as traversal_cache_test):
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
            "n_contents": 4,
        },
        {
            "tag": "Problem.Cause",
            "parent": "Problem",
            "description": "Causal factors",
            "n_contents": 2,
        },
        {
            "tag": "Problem.Cause.Scope",
            "parent": "Problem.Cause",
            "description": "Scope of cause",
            "n_contents": 1,
        },
        {
            "tag": "Problem.Solution",
            "parent": "Problem",
            "description": "Solutions",
            "n_contents": 1,
        },
        {
            "tag": "Problem.Impact",
            "parent": "Problem",
            "description": "Impacts",
            "n_contents": 0,
        },
        {
            "tag": "Problem.Impact.Scope",
            "parent": "Problem.Impact",
            "description": "Scope of impact",
            "n_contents": 0,
        },
    ]


def _standard_exemplars():
    """5 exemplars spread across the standard tree."""
    return [
        {
            "id": 1,
            "document": "doc1",
            "tag": "Problem",
            "content": "c1",
            "keywords": [],
            "content_hash": "a",
            "keyword_count": 0,
        },
        {
            "id": 2,
            "document": "doc2",
            "tag": "Problem.Cause",
            "content": "c2",
            "keywords": [],
            "content_hash": "b",
            "keyword_count": 0,
        },
        {
            "id": 3,
            "document": "doc3",
            "tag": "Problem.Cause.Scope",
            "content": "c3",
            "keywords": [],
            "content_hash": "c",
            "keyword_count": 0,
        },
        {
            "id": 4,
            "document": "doc4",
            "tag": "Problem.Solution",
            "content": "c4",
            "keywords": [],
            "content_hash": "d",
            "keyword_count": 0,
        },
        {
            "id": 5,
            "document": "doc5",
            "tag": "Problem.Impact",
            "content": "c5",
            "keywords": [],
            "content_hash": "e",
            "keyword_count": 0,
        },
    ]


def _create_tables(con):
    """Create test tables: traversal_cache and invalidation_log."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS traversal_cache (
            tag VARCHAR PRIMARY KEY,
            ancestors VARCHAR,
            descendants VARCHAR,
            subtree_exemplars VARCHAR,
            subtree_codes VARCHAR,
            subtree_themes VARCHAR,
            stale BOOLEAN DEFAULT FALSE
        );
    """
    )
    con.execute("CREATE SEQUENCE IF NOT EXISTS il_seq START 1;")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS invalidation_log (
            id INTEGER DEFAULT nextval('il_seq') PRIMARY KEY,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
            tag VARCHAR NOT NULL,
            reason VARCHAR NOT NULL
        );
    """
    )


class TestScopeRestriction(unittest.TestCase):
    """Test suite for get_scope_for_tag."""

    def setUp(self):
        import ontology.dag as dag_mod
        import ontology.traversal as trav_mod

        dag_mod._ONTOLOGY_GRAPH = None
        trav_mod.clear_traversal_cache()

        self.db_path = Path(tempfile.mktemp(suffix=".duckdb"))
        import duckdb

        con = duckdb.connect(str(self.db_path))
        _create_tables(con)
        con.close()

    def tearDown(self):
        import ontology.dag as dag_mod

        dag_mod._ONTOLOGY_GRAPH = None
        if self.db_path.exists():
            self.db_path.unlink()

    # --- leaf tag ---

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_leaf_tag_returns_self(self, mock_exemplars, mock_tags):
        """Leaf tag scope contains only the tag itself."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())
        from ontology.scope import get_scope_for_tag

        result = get_scope_for_tag("Problem.Cause.Scope", self.db_path)
        self.assertEqual(result, {"Problem.Cause.Scope"})

    # --- root tag ---

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_root_tag_returns_all(self, mock_exemplars, mock_tags):
        """Root tag scope includes all tags in the ontology."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())
        from ontology.scope import get_scope_for_tag

        result = get_scope_for_tag("Problem", self.db_path)
        expected = {
            "Problem",
            "Problem.Cause",
            "Problem.Cause.Scope",
            "Problem.Solution",
            "Problem.Impact",
            "Problem.Impact.Scope",
        }
        self.assertEqual(result, expected)

    # --- intermediate tag ---

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_intermediate_tag_subtree(self, mock_exemplars, mock_tags):
        """Intermediate tag scope = tag + its descendants only."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())
        from ontology.scope import get_scope_for_tag

        result = get_scope_for_tag("Problem.Cause", self.db_path)
        self.assertEqual(result, {"Problem.Cause", "Problem.Cause.Scope"})

    # --- unknown tag ---

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_unknown_tag_raises_key_error(self, mock_exemplars, mock_tags):
        """Unknown tag raises KeyError."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())
        from ontology.scope import get_scope_for_tag

        with self.assertRaises(KeyError):
            get_scope_for_tag("Nonexistent.Tag", self.db_path)

    # --- cache hit ---

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_cache_hit_returns_from_cache(self, mock_exemplars, mock_tags):
        """Pre-populated cache row returns result without recompute."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())
        # Pre-populate cache with leaf tag data
        import duckdb
        from ontology.scope import get_scope_for_tag

        con = duckdb.connect(str(self.db_path))
        con.execute(
            "INSERT INTO traversal_cache VALUES "
            "('Problem.Cause.Scope', '[]', '[]', '[3]', '[]', '[]', FALSE)"
        )
        con.close()

        result = get_scope_for_tag("Problem.Cause.Scope", self.db_path)
        self.assertEqual(result, {"Problem.Cause.Scope"})

    # --- cache miss ---

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_cache_miss_auto_recomputes(self, mock_exemplars, mock_tags):
        """Missing row triggers recompute and persists result."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())
        from ontology.scope import get_scope_for_tag

        result = get_scope_for_tag("Problem.Cause", self.db_path)
        self.assertEqual(result, {"Problem.Cause", "Problem.Cause.Scope"})

        # Verify row now exists in cache
        import duckdb

        con = duckdb.connect(str(self.db_path))
        row = con.execute(
            "SELECT 1 FROM traversal_cache WHERE tag = 'Problem.Cause' AND stale = FALSE"
        ).fetchone()
        con.close()
        self.assertIsNotNone(row)

    # --- cache stale ---

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_cache_stale_auto_recomputes(self, mock_exemplars, mock_tags):
        """Stale row triggers recompute and clears stale flag."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())

        import duckdb

        con = duckdb.connect(str(self.db_path))
        con.execute(
            "INSERT INTO traversal_cache VALUES "
            "('Problem.Impact', '[\"Problem\"]', '[\"Problem.Impact.Scope\"]', '[5]', '[]', '[]', TRUE)"
        )
        con.close()

        from ontology.scope import get_scope_for_tag

        result = get_scope_for_tag("Problem.Impact", self.db_path)
        self.assertEqual(result, {"Problem.Impact", "Problem.Impact.Scope"})

        con = duckdb.connect(str(self.db_path))
        stale = con.execute(
            "SELECT stale FROM traversal_cache WHERE tag = 'Problem.Impact'"
        ).fetchone()[0]
        con.close()
        self.assertFalse(stale)


# Note: Multiple-inheritance (diamond DAG) testing is deferred until the
# DAG builder supports multi-parent tags. The current builder assigns each
# tag a single parent (tree structure). NetworkX and get_subtree already
# handle DAGs correctly, so get_scope_for_tag will work once the builder
# is extended. See docs/plan/22-scope-restriction-helper.md.

if __name__ == "__main__":
    unittest.main()
