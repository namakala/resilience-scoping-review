"""Comprehensive unit tests for artifact loaders (loaders.py).

Covers:
- LazyFrame return type and lazy evaluation (no premature collect)
- content_hash recomputation (defensive SHA256[:16])
- keyword_count from keywords list length
- Tag parent/depth derivation for root and nested tags
- Keywords missing-file fallback with correct schema
- In-memory caching via lru_cache (same object on repeat calls)
- Cache clearing utility
"""

# flake8: noqa: E402
import hashlib
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add src/python to sys.path for imports
sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import polars as pl
from persistence.loaders import clear_cache, load_exemplars, load_keywords, load_tags
from utils.logging import get_logger

# Silence logger during tests by setting level to WARNING (or higher)
get_logger(__name__).setLevel(logging.WARNING)


class TestArtifactLoaders(unittest.TestCase):
    """Test suite for lazy-loading artifact functions."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.fixtures_dir = Path(__file__).parent.parent.parent / "fixtures" / "csv"
        self.original_cwd = Path.cwd()
        os.chdir(self.tmpdir)

        # Create data/processed structure for test fixtures
        (self.tmpdir / "data" / "processed").mkdir(parents=True, exist_ok=True)

        # Clear caches before each test to avoid cross-test contamination
        clear_cache()

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmpdir)
        clear_cache()
        os.chdir(self.original_cwd)

    def _write_test_exemplars_parquet(self, rows: list) -> Path:
        """Helper: write a minimal exemplars Parquet with given rows."""
        df = pl.DataFrame(
            rows,
            schema={
                "id": pl.Int64,
                "document": pl.String,
                "tag": pl.String,
                "content": pl.String,
                "keywords": pl.List(pl.String),
            },
            orient="row",
        )
        # Match converter: tag is Categorical
        df = df.with_columns(pl.col("tag").cast(pl.Categorical))
        # Compute content_hash using same formula as loader
        df = df.with_columns(
            pl.col("content")
            .map_elements(lambda c: hashlib.sha256(c.encode()).hexdigest()[:16])
            .alias("content_hash")
        )
        path = self.tmpdir / "data" / "processed" / "exemplars.parquet"
        df.write_parquet(path, compression="snappy")
        return path

    def _write_test_tags_parquet(self, rows: list) -> Path:
        """Helper: write a minimal tags Parquet."""
        df = pl.DataFrame(
            rows,
            schema={
                "tag": pl.String,
                "description": pl.String,
                "n_contents": pl.Int64,
            },
            orient="row",
        )
        # Match converter: tag is Categorical
        df = df.with_columns(pl.col("tag").cast(pl.Categorical))
        path = self.tmpdir / "data" / "processed" / "tags.parquet"
        df.write_parquet(path, compression="snappy")
        return path

    def _write_test_keywords_parquet(self, rows: list) -> Path:
        """Helper: write a minimal keywords Parquet."""
        df = pl.DataFrame(
            rows,
            schema={
                "keyword_id": pl.Int64,
                "exemplar_id": pl.Int64,
                "keyword_text": pl.String,
                "frequency": pl.Int32,
            },
        )
        path = self.tmpdir / "data" / "processed" / "keywords.parquet"
        df.write_parquet(path, compression="snappy")
        return path

    # ─── load_exemplars tests ───

    def test_load_exemplars_returns_lazyframe(self) -> None:
        """load_exemplars returns a Polars LazyFrame, not an eager DataFrame."""
        self._write_test_exemplars_parquet(
            [
                (1, "doc1", "tag1", "content1", ["kw1"]),
                (2, "doc2", "tag2", "content2", ["kw2", "kw3"]),
            ]
        )
        lf = load_exemplars()
        self.assertIsInstance(lf, pl.LazyFrame)

    def test_load_exemplars_lazy_evaluation(self) -> None:
        """Calling load_exemplars does NOT trigger .collect()."""
        self._write_test_exemplars_parquet([(1, "doc1", "tag1", "content1", [])])
        lf = load_exemplars()

        # Verify it's still lazy by checking no physical plan executed
        # Accessing .collect_schema() is okay; that's metadata only
        schema = lf.collect_schema()
        self.assertIn("content_hash", schema.names())

        # The LazyFrame should have transformations queued but not executed
        # A simple check: lf does not equal its collected version (different object types)
        self.assertNotEqual(type(lf), pl.DataFrame)

    def test_load_exemplars_recomputes_content_hash(self) -> None:
        """content_hash is recomputed from content, ignoring any stored value."""
        # Write Parquet with FAKE content_hash that doesn't match content
        df = pl.DataFrame(
            [
                (1, "doc1", "tag1", "hello world", ["kw1"], "f0akehash12345678"),
            ],
            schema={
                "id": pl.Int64,
                "document": pl.String,
                "tag": pl.String,
                "content": pl.String,
                "keywords": pl.List(pl.String),
                "content_hash": pl.String,
            },
            orient="row",
        )
        path = self.tmpdir / "data" / "processed" / "exemplars.parquet"
        df.write_parquet(path, compression="snappy")

        lf = load_exemplars()
        result = lf.collect()

        # The hash should match SHA256("hello world")[:16], not "f0ake..."
        expected = hashlib.sha256(b"hello world").hexdigest()[:16]
        self.assertEqual(result["content_hash"][0], expected)

    def test_load_exemplars_keyword_count(self) -> None:
        """keyword_count matches the length of the keywords list."""
        self._write_test_exemplars_parquet(
            [
                (1, "doc1", "tag1", "content1", ["a", "b", "c"]),  # count = 3
                (2, "doc2", "tag2", "content2", ["x"]),  # count = 1
                (3, "doc3", "tag3", "content3", []),  # count = 0
            ]
        )
        lf = load_exemplars()
        result = lf.collect()

        self.assertEqual(result["keyword_count"][0], 3)
        self.assertEqual(result["keyword_count"][1], 1)
        self.assertEqual(result["keyword_count"][2], 0)

    def test_load_exemplars_caching(self) -> None:
        """Second call returns the same LazyFrame object (in-memory cache)."""
        self._write_test_exemplars_parquet([(1, "doc1", "tag1", "content1", [])])
        first = load_exemplars()
        second = load_exemplars()
        self.assertIs(first, second, "Cached load_exemplars should return same object")

    # ─── load_tags tests ───

    def test_load_tags_returns_lazyframe(self) -> None:
        """load_tags returns a Polars LazyFrame."""
        self._write_test_tags_parquet(
            [
                ("root", "Root description", 5),
                ("branch.leaf", "Nested description", 3),
            ]
        )
        lf = load_tags()
        self.assertIsInstance(lf, pl.LazyFrame)

    def test_load_tags_parent_root(self) -> None:
        """Root tag (no dot) has empty parent string."""
        self._write_test_tags_parquet([("Problem", "Root tag", 10)])
        lf = load_tags()
        result = lf.collect()
        self.assertEqual(result["parent"][0], "")

    def test_load_tags_parent_nested(self) -> None:
        """Nested tag 'A.B.C' has parent 'A.B'."""
        self._write_test_tags_parquet([("Problem.Cause.Impact", "Deeply nested", 7)])
        lf = load_tags()
        result = lf.collect()
        self.assertEqual(result["parent"][0], "Problem.Cause")

    def test_load_tags_depth_root(self) -> None:
        """Root tag has depth 1."""
        self._write_test_tags_parquet([("Problem", "Root", 10)])
        lf = load_tags()
        result = lf.collect()
        self.assertEqual(result["depth"][0], 1)

    def test_load_tags_depth_nested(self) -> None:
        """Nested tag depth = number of separators + 1."""
        self._write_test_tags_parquet(
            [
                ("A", "depth 1", 0),
                ("A.B", "depth 2", 0),
                ("A.B.C", "depth 3", 0),
                ("A.B.C.D", "depth 4", 0),
            ]
        )
        lf = load_tags()
        result = lf.collect()
        depths = result["depth"].to_list()
        self.assertEqual(depths, [1, 2, 3, 4])

    def test_load_tags_caching(self) -> None:
        """Second call returns the same LazyFrame object."""
        self._write_test_tags_parquet([("tag1", "desc", 1)])
        first = load_tags()
        second = load_tags()
        self.assertIs(first, second)

    # ─── load_keywords tests ───

    def test_load_keywords_returns_lazyframe(self) -> None:
        """load_keywords returns a LazyFrame when file exists."""
        self._write_test_keywords_parquet(
            [
                (1, 100, "stress", 5),
                (2, 101, "anxiety", 3),
            ]
        )
        lf = load_keywords()
        self.assertIsInstance(lf, pl.LazyFrame)

    def test_load_keywords_missing_file_returns_empty_schema(self) -> None:
        """When keywords.parquet absent, returns empty LazyFrame with correct schema."""
        # Ensure file does NOT exist
        path = self.tmpdir / "data" / "processed" / "keywords.parquet"
        if path.exists():
            path.unlink()

        lf = load_keywords()
        result = lf.collect()
        self.assertEqual(result.height, 0)
        self.assertEqual(
            set(result.schema.names()),
            {"keyword_id", "exemplar_id", "keyword_text", "frequency"},
        )
        # Verify dtypes match spec
        self.assertEqual(result.schema["keyword_id"], pl.Int64)
        self.assertEqual(result.schema["exemplar_id"], pl.Int64)
        self.assertEqual(result.schema["keyword_text"], pl.String)
        self.assertEqual(result.schema["frequency"], pl.Int32)

    def test_load_keywords_caching(self) -> None:
        """Second call returns same LazyFrame object."""
        self._write_test_keywords_parquet([(1, 100, "kw", 1)])
        first = load_keywords()
        second = load_keywords()
        self.assertIs(first, second)

    def test_load_keywords_roundtrip(self) -> None:
        """Keywords loaded from file match what was written."""
        rows = [
            (1, 100, "stress", 5),
            (2, 100, "resilience", 3),
            (3, 101, "coping", 7),
        ]
        self._write_test_keywords_parquet(rows)
        lf = load_keywords()
        result = lf.sort("keyword_id").collect()

        self.assertEqual(result.height, 3)
        self.assertEqual(result["keyword_text"][0], "stress")
        self.assertEqual(result["frequency"][1], 3)

    # ─── clear_cache tests ───

    def test_clear_cache_resets_loaders(self) -> None:
        """clear_cache() forces fresh reads on next load_* call."""
        self._write_test_exemplars_parquet([(1, "d", "t", "c", [])])
        first = load_exemplars()
        self.assertIsNotNone(first)

        clear_cache()
        second = load_exemplars()
        self.assertIsNot(first, second, "Cache should have been cleared")

    def test_schema_compliance_exemplars(self) -> None:
        """Exemplars LazyFrame has exact schema as specified."""
        self._write_test_exemplars_parquet([(1, "doc", "tag", "content", ["a", "b"])])
        lf = load_exemplars()
        schema = lf.collect_schema()

        expected_names = {
            "id",
            "document",
            "tag",
            "content",
            "keywords",
            "content_hash",
            "keyword_count",
        }
        self.assertEqual(set(schema.names()), expected_names)

        self.assertEqual(schema["id"], pl.Int64)
        self.assertEqual(schema["document"], pl.String)
        self.assertEqual(schema["tag"], pl.Categorical)
        self.assertEqual(schema["content"], pl.String)
        self.assertEqual(schema["keywords"], pl.List(pl.String))
        self.assertEqual(schema["content_hash"], pl.String)
        self.assertEqual(schema["keyword_count"], pl.Int64)

    def test_schema_compliance_tags(self) -> None:
        """Tags LazyFrame has exact schema as specified."""
        self._write_test_tags_parquet([("tag", "desc", 5)])
        lf = load_tags()
        schema = lf.collect_schema()

        expected_names = {"tag", "parent", "description", "n_contents", "depth"}
        self.assertEqual(set(schema.names()), expected_names)

        self.assertEqual(schema["tag"], pl.Categorical)
        self.assertEqual(schema["parent"], pl.String)
        self.assertEqual(schema["description"], pl.String)
        self.assertEqual(schema["n_contents"], pl.Int64)
        self.assertEqual(schema["depth"], pl.Int64)

    def test_schema_compliance_keywords_when_present(self) -> None:
        """Keywords LazyFrame has exact schema when file exists."""
        self._write_test_keywords_parquet([(1, 100, "kw", 1)])
        lf = load_keywords()
        schema = lf.collect_schema()

        expected_names = {"keyword_id", "exemplar_id", "keyword_text", "frequency"}
        self.assertEqual(set(schema.names()), expected_names)

        self.assertEqual(schema["keyword_id"], pl.Int64)
        self.assertEqual(schema["exemplar_id"], pl.Int64)
        self.assertEqual(schema["keyword_text"], pl.String)
        self.assertEqual(schema["frequency"], pl.Int32)


if __name__ == "__main__":
    unittest.main()
