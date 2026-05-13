"""Unit tests for DuckDB-backed traversal cache (Feature 19).

Test coverage:
- build_traversal_cache: populates all tags, correct ancestors/descendants,
  correct subtree_exemplars, empty subtree_codes/themes, empty DAG handling
- get_cached_subtree: returns full dict, fallback on missing, fallback on
  stale, unknown tag raises KeyError
- invalidate_cache_for_tag: sets stale flag
- clear_duckdb_cache: empties table
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


# Standard test tree (same as ontology_traversal_test):
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


def _create_cache_table(con):
    """Create traversal_cache table in the test DuckDB database."""
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


class TestTraversalCache(unittest.TestCase):
    """Test suite for DuckDB-backed traversal cache."""

    def setUp(self):
        import ontology.dag as dag_mod
        import ontology.traversal as trav_mod

        dag_mod._ONTOLOGY_GRAPH = None
        trav_mod.clear_traversal_cache()

        self.db_path = Path(tempfile.mktemp(suffix=".duckdb"))
        import duckdb

        con = duckdb.connect(str(self.db_path))
        _create_cache_table(con)
        con.close()

    def tearDown(self):
        import ontology.dag as dag_mod

        dag_mod._ONTOLOGY_GRAPH = None
        if self.db_path.exists():
            self.db_path.unlink()

    # --- build_traversal_cache ---

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_build_populates_all_tags(self, mock_exemplars, mock_tags):
        """After build_traversal_cache, all 6 tags have rows."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())

        from ontology.cache import build_traversal_cache

        count = build_traversal_cache(self.db_path)
        self.assertEqual(count, 6)

        import duckdb

        con = duckdb.connect(str(self.db_path))
        rows = con.execute("SELECT COUNT(*) FROM traversal_cache").fetchone()[0]
        con.close()
        self.assertEqual(rows, 6)

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_cache_ancestors_correct(self, mock_exemplars, mock_tags):
        """Ancestor JSON deserialized matches expected values."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())

        from ontology.cache import build_traversal_cache

        build_traversal_cache(self.db_path)

        import duckdb

        con = duckdb.connect(str(self.db_path))
        row = con.execute(
            "SELECT ancestors FROM traversal_cache " "WHERE tag = 'Problem.Cause.Scope'"
        ).fetchone()
        con.close()
        self.assertEqual(json.loads(row[0]), ["Problem", "Problem.Cause"])

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_cache_descendants_correct(self, mock_exemplars, mock_tags):
        """Descendant JSON for root includes all 5 other tags."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())

        from ontology.cache import build_traversal_cache

        build_traversal_cache(self.db_path)

        import duckdb

        con = duckdb.connect(str(self.db_path))
        row = con.execute(
            "SELECT descendants FROM traversal_cache " "WHERE tag = 'Problem'"
        ).fetchone()
        con.close()
        desc = json.loads(row[0])
        self.assertEqual(len(desc), 5)
        self.assertIn("Problem.Cause", desc)
        self.assertIn("Problem.Cause.Scope", desc)
        self.assertIn("Problem.Solution", desc)
        self.assertIn("Problem.Impact", desc)
        self.assertIn("Problem.Impact.Scope", desc)

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_subtree_exemplars_computed(self, mock_exemplars, mock_tags):
        """Exemplar IDs match tags within the tag's subtree."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())

        from ontology.cache import build_traversal_cache

        build_traversal_cache(self.db_path)

        import duckdb

        con = duckdb.connect(str(self.db_path))
        row = con.execute(
            "SELECT subtree_exemplars FROM traversal_cache "
            "WHERE tag = 'Problem.Cause'"
        ).fetchone()
        con.close()
        # Problem.Cause subtree: Problem.Cause (id=2), Problem.Cause.Scope (id=3)
        self.assertEqual(json.loads(row[0]), [2, 3])

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_subtree_codes_themes_initially_empty(self, mock_exemplars, mock_tags):
        """subtree_codes and subtree_themes are empty JSON arrays."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())

        from ontology.cache import build_traversal_cache

        build_traversal_cache(self.db_path)

        import duckdb

        con = duckdb.connect(str(self.db_path))
        rows = con.execute(
            "SELECT subtree_codes, subtree_themes FROM traversal_cache"
        ).fetchall()
        con.close()
        for codes, themes in rows:
            self.assertEqual(json.loads(codes), [])
            self.assertEqual(json.loads(themes), [])

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_build_empty_dag(self, mock_exemplars, mock_tags):
        """Empty DAG returns 0 without error."""
        mock_tags.return_value = _make_tags_lf([])
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())

        from ontology.cache import build_traversal_cache

        count = build_traversal_cache(self.db_path)
        self.assertEqual(count, 0)

    # --- get_cached_subtree ---

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_get_cached_subtree_returns_full_dict(self, mock_exemplars, mock_tags):
        """get_cached_subtree returns dict with all expected keys."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())

        from ontology.cache import build_traversal_cache, get_cached_subtree

        build_traversal_cache(self.db_path)

        result = get_cached_subtree("Problem.Cause.Scope", self.db_path)
        self.assertEqual(result["tag"], "Problem.Cause.Scope")
        self.assertEqual(result["ancestors"], ["Problem", "Problem.Cause"])
        self.assertEqual(result["descendants"], [])
        self.assertEqual(result["subtree_exemplars"], [3])
        self.assertEqual(result["subtree_codes"], [])
        self.assertEqual(result["subtree_themes"], [])

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_get_cached_subtree_fallback_on_missing(self, mock_exemplars, mock_tags):
        """Missing row triggers recompute and returns correct data."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())

        from ontology.cache import get_cached_subtree

        result = get_cached_subtree("Problem", self.db_path)
        self.assertEqual(result["tag"], "Problem")

        import duckdb

        con = duckdb.connect(str(self.db_path))
        row = con.execute(
            "SELECT 1 FROM traversal_cache " "WHERE tag = 'Problem' AND stale = FALSE"
        ).fetchone()
        con.close()
        self.assertIsNotNone(row)

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_get_cached_subtree_fallback_on_stale(self, mock_exemplars, mock_tags):
        """Stale row triggers recompute and clears stale flag."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())

        import duckdb

        con = duckdb.connect(str(self.db_path))
        con.execute(
            "INSERT INTO traversal_cache VALUES "
            "('Problem', '[]', '[]', '[]', '[]', '[]', TRUE)"
        )
        con.close()

        from ontology.cache import get_cached_subtree

        result = get_cached_subtree("Problem", self.db_path)
        self.assertEqual(result["tag"], "Problem")

        con = duckdb.connect(str(self.db_path))
        stale = con.execute(
            "SELECT stale FROM traversal_cache WHERE tag = 'Problem'"
        ).fetchone()[0]
        con.close()
        self.assertFalse(stale)

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_get_cached_subtree_unknown_tag(self, mock_exemplars, mock_tags):
        """Unknown tag raises KeyError."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())

        from ontology.cache import get_cached_subtree

        with self.assertRaises(KeyError):
            get_cached_subtree("Nonexistent.Tag", self.db_path)

    # --- invalidate_cache_for_tag ---

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_invalidate_sets_stale_flag(self, mock_exemplars, mock_tags):
        """After invalidate_cache_for_tag, stale=TRUE for that tag."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())

        from ontology.cache import build_traversal_cache, invalidate_cache_for_tag

        build_traversal_cache(self.db_path)
        invalidate_cache_for_tag("Problem", self.db_path)

        import duckdb

        con = duckdb.connect(str(self.db_path))
        stale = con.execute(
            "SELECT stale FROM traversal_cache WHERE tag = 'Problem'"
        ).fetchone()[0]
        con.close()
        self.assertTrue(stale)

    # --- clear_duckdb_cache ---

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_clear_cache_empties_table(self, mock_exemplars, mock_tags):
        """After clear_duckdb_cache, traversal_cache is empty."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())

        from ontology.cache import build_traversal_cache, clear_duckdb_cache

        build_traversal_cache(self.db_path)
        clear_duckdb_cache(self.db_path)

        import duckdb

        con = duckdb.connect(str(self.db_path))
        count = con.execute("SELECT COUNT(*) FROM traversal_cache").fetchone()[0]
        con.close()
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
