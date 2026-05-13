"""Comprehensive unit tests for BM25 index module.

Covers:
- Tokenizer pipeline with all toggle combinations
- Index building from keywords corpus
- Pickle round-trip preservation of scores (±1e-6)
- Score normalization to [0, 1]; equal scores produce all zeros
- Metadata presence: version, created_at (ISO), corpus_hash, tokenizer_config
- Corpus hash mismatch detection (IndexCorruptedError)
- Empty corpus handling (build succeeds, queries return empty)
- Storage size check (< 100 MB for 1000 exemplars)
- get_top_n returns sorted results limited to n
- Config parsing: invalid toggle raises ValueError
"""

# flake8: noqa: E402
import hashlib
import logging
import os
import pickle
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

# Add src/python to sys.path (4 levels up: semantic -> unit -> tests -> project root)
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src" / "python"))

import numpy as np
import polars as pl

# Set PROCESSED_DATA_PATH to a temp location before importing module
TEST_DIR = Path(tempfile.mkdtemp())
os.environ["PROCESSED_DATA_PATH"] = str(TEST_DIR)

from persistence.loaders import clear_cache as clear_loader_cache
from persistence.loaders import configure_paths, load_keywords
from semantic.api import get_index_info, get_scores, get_top_n
from semantic.cache import clear_cache
from semantic.exceptions import BM25IndexError, IndexCorruptedError
from semantic.index_builder import build_index
from semantic.persistence import load_bm25, save_bm25
from semantic.tokenizer import _TOKENIZER, _build_tokenizer, _parse_tokenizer_config
from utils.logging import get_logger

get_logger(__name__).setLevel(logging.WARNING)


class TestBM25Tokenizer(unittest.TestCase):
    """Tokenizer pipeline tests."""

    def test_default_tokenizer_splits_and_lowercases(self):
        # Default toggles: lowercase,split_by_space (no punctuation stripping)
        text = "Hello WORLD, stop THIS!"
        tokens = _TOKENIZER(text)
        # Lowercase applied; split on space keeps punctuation attached
        self.assertIn("hello", tokens)
        self.assertIn("world,", tokens)
        self.assertIn("stop", tokens)
        self.assertIn("this!", tokens)

    def test_tokenizer_invalid_toggle_raises(self):
        with self.assertRaises(ValueError):
            _parse_tokenizer_config("lowercase,unknown_toggle,split")

    def test_tokenizer_lowercase_toggle(self):
        toggles = _parse_tokenizer_config("lowercase,split_by_space")
        tokenizer = _build_tokenizer(toggles)
        tokens = tokenizer("HELLO World")
        self.assertEqual(set(tokens), {"hello", "world"})

    def test_tokenizer_no_lowercase(self):
        toggles = _parse_tokenizer_config("split_by_space")
        tokenizer = _build_tokenizer(toggles)
        tokens = tokenizer("HELLO world")
        self.assertIn("HELLO", tokens)
        self.assertIn("world", tokens)

    def test_tokenizer_missing_split_by_space_raises(self):
        with self.assertRaises(ValueError):
            _build_tokenizer(["lowercase"])

    def test_tokenizer_strip_punctuation(self):
        toggles = _parse_tokenizer_config("strip_punctuation,split_by_space")
        tokenizer = _build_tokenizer(toggles)
        tokens = tokenizer("hello, world! test.")
        self.assertNotIn(",", "".join(tokens))
        self.assertNotIn("!", "".join(tokens))
        self.assertIn("hello", tokens)
        self.assertIn("world", tokens)

    def test_tokenizer_remove_stopword(self):
        toggles = _parse_tokenizer_config("lowercase,split_by_space,remove_stopword")
        tokenizer = _build_tokenizer(toggles)
        tokens = tokenizer("the quick brown fox jumps over the lazy dog")
        self.assertNotIn("the", tokens)
        self.assertNotIn("over", tokens)  # "over" is a stopword in our list
        self.assertIn("quick", tokens)
        self.assertIn("fox", tokens)


class TestBM25IndexBuildAndSave(unittest.TestCase):
    """Index construction and persistence tests."""

    def setUp(self):
        # Create a fresh temporary directory for this test
        self.tmpdir = Path(tempfile.mkdtemp())
        # Set PROCESSED_DATA_PATH environment variable
        os.environ["PROCESSED_DATA_PATH"] = str(self.tmpdir)
        # Reconfigure loaders module to use the new path (since it may have been imported earlier)
        configure_paths(self.tmpdir)
        # Also configure bm25_index paths? It uses env var at runtime, so fine.
        self.test_path = self.tmpdir / "bm25_index.pkl"
        # Clear caches
        clear_cache()
        clear_loader_cache()
        # Clean up any existing files (shouldn't be any)
        if self.test_path.exists():
            self.test_path.unlink()
        keywords_path = self.tmpdir / "keywords.parquet"
        if keywords_path.exists():
            keywords_path.unlink()
        # Switch cwd to temp
        self.original_cwd = Path.cwd()
        os.chdir(self.tmpdir)

    def tearDown(self):
        import shutil

        os.chdir(self.original_cwd)
        # Clean up generated files
        if self.test_path.exists():
            self.test_path.unlink()
        keywords_path = self.tmpdir / "keywords.parquet"
        if keywords_path.exists():
            keywords_path.unlink()
        # Remove the temp directory
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        clear_cache()
        clear_loader_cache()

    def _write_keywords_parquet(self, rows):
        """Helper: write a keywords Parquet with given rows."""
        df = pl.DataFrame(
            {
                "keyword_id": [r[0] for r in rows],
                "exemplar_id": [r[1] for r in rows],
                "keyword_text": [r[2] for r in rows],
                "frequency": [r[3] for r in rows],
            },
            schema={
                "keyword_id": pl.Int64,
                "exemplar_id": pl.Int64,
                "keyword_text": pl.String,
                "frequency": pl.Int32,
            },
        )
        # Write to the configured processed data directory
        path = self.tmpdir / "keywords.parquet"
        df.write_parquet(path, compression="snappy")
        return path

    def test_build_index_with_small_corpus(self):
        self._write_keywords_parquet(
            [
                (1, 101, "stress", 5),
                (2, 101, "anxiety", 3),
                (3, 102, "resilience", 4),
                (4, 103, "coping", 2),
            ]
        )
        build_index(force_rebuild=True)
        self.assertTrue(self.test_path.exists())
        data = load_bm25()
        self.assertEqual(len(data["corpus"]), 3)  # 3 exemplars (101, 102, 103)
        self.assertIn(101, data["entity_map"])
        self.assertIn(102, data["entity_map"])
        self.assertIn(103, data["entity_map"])

    def test_save_and_load_roundtrip_preserves_scores(self):
        self._write_keywords_parquet(
            [
                (1, 1, "alpha", 1),
                (2, 1, "beta", 1),
                (3, 2, "gamma", 1),
            ]
        )
        build_index(force_rebuild=True)
        original_data = load_bm25()

        # Reload fresh from disk
        clear_cache()
        loaded_data = load_bm25()

        # Compare scores for a sample query
        query = "alpha beta gamma"
        orig_scores = original_data["bm25_object"].get_scores(_TOKENIZER(query))
        load_scores = loaded_data["bm25_object"].get_scores(_TOKENIZER(query))
        np.testing.assert_allclose(orig_scores, load_scores, atol=1e-6)

    def test_get_scores_normalized_range(self):
        self._write_keywords_parquet(
            [
                (1, 1, "apple", 1),
                (2, 2, "banana", 1),
                (3, 3, "cherry", 1),
            ]
        )
        build_index(force_rebuild=True)
        scores = get_scores("fruit apple banana")
        for score in scores.values():
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)

    def test_get_scores_all_equal_returns_zeros(self):
        # Only one document, or all docs have same score for query
        self._write_keywords_parquet(
            [
                (1, 1, "test", 1),
            ]
        )
        build_index(force_rebuild=True)
        scores = get_scores("nonexistent keyword")
        for score in scores.values():
            self.assertEqual(score, 0.0)

    def test_get_top_n_returns_sorted_limited(self):
        self._write_keywords_parquet(
            [
                (1, 1, "alpha", 1),
                (2, 2, "beta", 1),
                (3, 3, "gamma", 1),
            ]
        )
        build_index(force_rebuild=True)
        top3 = get_top_n("alpha", n=3)
        self.assertEqual(len(top3), 3)
        # Verify sorted descending
        scores = [s for _, s in top3]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_metadata_contains_required_fields(self):
        self._write_keywords_parquet(
            [
                (1, 1, "kw", 1),
            ]
        )
        build_index(force_rebuild=True)
        info = get_index_info()
        self.assertIn("version", info)
        self.assertIn("created_at", info)
        self.assertIn("corpus_hash", info)
        self.assertIn("tokenizer_config", info)
        self.assertEqual(info["version"], "1.0")
        # ISO format check
        datetime.fromisoformat(info["created_at"])  # should not raise

    def test_corpus_hash_mismatch_raises_corrupted_error(self):
        self._write_keywords_parquet(
            [
                (1, 1, "kw1", 1),
                (2, 2, "kw2", 1),
            ]
        )
        build_index(force_rebuild=True)

        # Tamper: change corpus_hash in saved file
        clear_cache()
        with open(self.test_path, "rb") as f:
            data = pickle.load(f)
        data["metadata"]["corpus_hash"] = "tamperedhash123"

        with open(self.test_path, "wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)

        clear_cache()
        with self.assertRaises(IndexCorruptedError):
            load_bm25()

    def test_build_index_with_empty_corpus(self):
        # keywords.parquet exists but empty
        self._write_keywords_parquet([])
        build_index(force_rebuild=True)
        data = load_bm25()
        self.assertEqual(len(data["corpus"]), 0)
        self.assertEqual(len(data["entity_map"]), 0)
        scores = get_scores("anything")
        self.assertEqual(scores, {})

    def test_storage_size_under_100mb_for_1000_exemplars(self):
        # Generate 1000 exemplars × ~5 keywords each
        rows = []
        kw_id = 0
        for exemplar_id in range(1, 1001):
            for j in range(5):
                kw_id += 1
                rows.append((kw_id, exemplar_id, f"kw{exemplar_id}_{j}", 1))
        self._write_keywords_parquet(rows)
        build_index(force_rebuild=True)
        size = os.path.getsize(self.test_path)
        self.assertLess(size, 100 * 1024 * 1024, f"Index size {size} exceeds 100 MB")

    def test_invalid_tokenizer_config_raises_at_import(self):
        # Cannot easily test module-level init; test parser directly
        with self.assertRaises(ValueError):
            _parse_tokenizer_config("lowercase,invalid_toggle,split")


if __name__ == "__main__":
    # Ensure TEST_DIR exists
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    unittest.main()
