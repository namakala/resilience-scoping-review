"""Unit tests for incremental cache invalidation (Feature 20).

Test coverage:
- invalidate_cache_for_tag: sets stale on tag, propagates to descendants
- invalidate_cache_for_tags: bulk invalidation, single transaction
- Audit log entries created for each invalidation
- Unknown tag raises KeyError
- get_cached_subtree recomputes after invalidation
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
        {"tag": "Problem", "parent": "", "description": "Root", "n_contents": 4},
        {
            "tag": "Problem.Cause",
            "parent": "Problem",
            "description": "Causes",
            "n_contents": 2,
        },
        {
            "tag": "Problem.Cause.Scope",
            "parent": "Problem.Cause",
            "description": "Cause scope",
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
            "description": "Impact scope",
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
    """Create sequences, traversal_cache and invalidation_log tables."""
    con.execute("CREATE SEQUENCE IF NOT EXISTS il_seq START 1;")
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


class TestInvalidation(unittest.TestCase):
    """Test suite for incremental cache invalidation."""

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

    def _build_cache(self):
        """Helper: build traversal cache with standard tree."""
        from ontology.cache import build_traversal_cache

        build_traversal_cache(self.db_path)

    # --- invalidate_cache_for_tag ---

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_invalidate_sets_stale_on_tag(self, mock_exemplars, mock_tags):
        """invalidate_cache_for_tag sets stale=TRUE for the target tag."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())
        self._build_cache()

        from ontology.invalidation import invalidate_cache_for_tag

        invalidate_cache_for_tag("Problem.Cause", self.db_path)

        import duckdb

        con = duckdb.connect(str(self.db_path))
        stale = con.execute(
            "SELECT stale FROM traversal_cache WHERE tag = 'Problem.Cause'"
        ).fetchone()[0]
        con.close()
        self.assertTrue(stale)

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_invalidate_propagates_to_descendants(self, mock_exemplars, mock_tags):
        """Descendants of the invalidated tag also get stale=TRUE."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())
        self._build_cache()

        from ontology.invalidation import invalidate_cache_for_tag

        invalidate_cache_for_tag("Problem.Cause", self.db_path)

        import duckdb

        con = duckdb.connect(str(self.db_path))
        rows = dict(
            con.execute(
                "SELECT tag, stale FROM traversal_cache "
                "WHERE tag IN ('Problem.Cause', 'Problem.Cause.Scope')"
            ).fetchall()
        )
        con.close()
        self.assertTrue(rows["Problem.Cause"])
        self.assertTrue(rows["Problem.Cause.Scope"])

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_invalidate_leaf_tag_no_propagation(self, mock_exemplars, mock_tags):
        """Leaf tag only marks itself stale, not its parent or siblings."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())
        self._build_cache()

        from ontology.invalidation import invalidate_cache_for_tag

        invalidate_cache_for_tag("Problem.Cause.Scope", self.db_path)

        import duckdb

        con = duckdb.connect(str(self.db_path))
        rows = dict(
            con.execute(
                "SELECT tag, stale FROM traversal_cache "
                "WHERE tag IN ('Problem', 'Problem.Cause', 'Problem.Cause.Scope', "
                "'Problem.Solution')"
            ).fetchall()
        )
        con.close()
        self.assertFalse(rows["Problem"])
        self.assertFalse(rows["Problem.Cause"])
        self.assertTrue(rows["Problem.Cause.Scope"])
        self.assertFalse(rows["Problem.Solution"])

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_invalidate_root_tag_all_descendants(self, mock_exemplars, mock_tags):
        """Root tag propagates stale to all other tags."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())
        self._build_cache()

        from ontology.invalidation import invalidate_cache_for_tag

        invalidate_cache_for_tag("Problem", self.db_path)

        import duckdb

        con = duckdb.connect(str(self.db_path))
        rows = dict(con.execute("SELECT tag, stale FROM traversal_cache").fetchall())
        con.close()
        self.assertTrue(rows["Problem"])
        self.assertTrue(rows["Problem.Cause"])
        self.assertTrue(rows["Problem.Cause.Scope"])
        self.assertTrue(rows["Problem.Solution"])
        self.assertTrue(rows["Problem.Impact"])
        self.assertTrue(rows["Problem.Impact.Scope"])

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_invalidate_logs_audit_entry(self, mock_exemplars, mock_tags):
        """Invalidation creates an audit log entry with tag and reason."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())
        self._build_cache()

        from ontology.invalidation import invalidate_cache_for_tag

        invalidate_cache_for_tag("Problem.Cause", self.db_path, "tag_merge")

        import duckdb

        con = duckdb.connect(str(self.db_path))
        entries = con.execute(
            "SELECT tag, reason FROM invalidation_log ORDER BY id"
        ).fetchall()
        con.close()
        tags_logged = [e[0] for e in entries]
        reasons = set(e[1] for e in entries)
        self.assertIn("Problem.Cause", tags_logged)
        self.assertIn("Problem.Cause.Scope", tags_logged)
        # All entries for same call share the reason
        self.assertEqual(reasons, {"tag_merge"})

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_invalidate_unknown_tag_raises(self, mock_exemplars, mock_tags):
        """Unknown tag raises KeyError."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())
        self._build_cache()

        from ontology.invalidation import invalidate_cache_for_tag

        with self.assertRaises(KeyError):
            invalidate_cache_for_tag("Nonexistent.Tag", self.db_path)

    # --- invalidate_cache_for_tags (bulk) ---

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_invalidate_bulk_multiple_tags(self, mock_exemplars, mock_tags):
        """Bulk invalidation marks multiple tag branches as stale."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())
        self._build_cache()

        from ontology.invalidation import invalidate_cache_for_tags

        invalidate_cache_for_tags(
            ["Problem.Cause", "Problem.Impact"],
            self.db_path,
            "bulk_test",
        )

        import duckdb

        con = duckdb.connect(str(self.db_path))
        stale_tags = set(
            row[0]
            for row in con.execute(
                "SELECT tag FROM traversal_cache WHERE stale = TRUE"
            ).fetchall()
        )
        con.close()
        expected = {
            "Problem.Cause",
            "Problem.Cause.Scope",
            "Problem.Impact",
            "Problem.Impact.Scope",
        }
        self.assertEqual(stale_tags, expected)

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_invalidate_bulk_single_transaction(self, mock_exemplars, mock_tags):
        """Bulk invalidation commits atomically — all or nothing."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())
        self._build_cache()

        import duckdb

        # Pre-seed a log entry to verify rollback doesn't affect prior data
        con = duckdb.connect(str(self.db_path))
        con.execute(
            "INSERT INTO invalidation_log (id, tag, reason) VALUES "
            "(999, 'pre_seed', 'setup')"
        )
        con.close()

        from ontology.invalidation import invalidate_cache_for_tags

        # Unknown tag should cause rollback of entire batch
        with self.assertRaises(KeyError):
            invalidate_cache_for_tags(
                ["Problem.Cause", "Unknown.Tag"],
                self.db_path,
                "should_rollback",
            )

        con = duckdb.connect(str(self.db_path))
        # Pre-seed entry should still exist
        pre_seed = con.execute(
            "SELECT tag FROM invalidation_log WHERE id = 999"
        ).fetchone()
        # Problem.Cause should NOT have been marked stale
        stale = con.execute(
            "SELECT stale FROM traversal_cache WHERE tag = 'Problem.Cause'"
        ).fetchone()[0]
        # No entries for the rollback batch
        rollback_entries = con.execute(
            "SELECT COUNT(*) FROM invalidation_log WHERE reason = 'should_rollback'"
        ).fetchone()[0]
        con.close()

        self.assertIsNotNone(pre_seed)
        self.assertFalse(stale)
        self.assertEqual(rollback_entries, 0)

    # --- Integration with get_cached_subtree ---

    @patch("ontology.dag.load_tags")
    @patch("ontology.cache.load_exemplars")
    def test_get_cached_subtree_recomputes_after_invalidate(
        self, mock_exemplars, mock_tags
    ):
        """After invalidation, get_cached_subtree recomputes and clears stale."""
        mock_tags.return_value = _make_tags_lf(_standard_tree())
        mock_exemplars.return_value = _make_exemplars_lf(_standard_exemplars())
        self._build_cache()

        from ontology.cache import get_cached_subtree
        from ontology.invalidation import invalidate_cache_for_tag

        invalidate_cache_for_tag("Problem.Cause", self.db_path)

        # Trigger recompute
        result = get_cached_subtree("Problem.Cause", self.db_path)

        self.assertEqual(result["tag"], "Problem.Cause")
        self.assertEqual(result["ancestors"], ["Problem"])

        import duckdb

        con = duckdb.connect(str(self.db_path))
        stale = con.execute(
            "SELECT stale FROM traversal_cache WHERE tag = 'Problem.Cause'"
        ).fetchone()[0]
        con.close()
        self.assertFalse(stale)


if __name__ == "__main__":
    unittest.main()
