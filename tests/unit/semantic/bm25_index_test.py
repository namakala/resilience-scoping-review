"""Unit tests for BM25 index building and scoring (pure versions).

Covers:
- Tokenizer pipeline with all toggle combinations
- build_index(keywords_lf, config) returns correct dict structure
- get_scores(query, index) normalization to [0, 1]
- Empty corpus handling
- get_top_n sorted and limited
- Metadata presence
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

import polars as pl  # noqa: E402
from semantic.api import get_index_info, get_scores, get_top_n  # noqa: E402
from semantic.index_builder import build_index  # noqa: E402
from semantic.tokenizer import _build_tokenizer, _parse_tokenizer_config  # noqa: E402


def _make_keywords_lf(rows: list) -> pl.LazyFrame:
    """Create keyword LazyFrame from (id, exemplar_id, text, freq) rows."""
    return pl.DataFrame(
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
    ).lazy()


class TestBM25Tokenizer(unittest.TestCase):
    """Tokenizer pipeline tests — unchanged from pre-refactor."""

    def test_default_tokenizer_splits_and_lowercases(self):
        text = "Hello WORLD, stop THIS!"
        # Build tokenizer explicitly instead of using module-level _TOKENIZER
        # which picks up BM25_TOKENIZER_CONFIG from .env
        tokenizer = _build_tokenizer(
            _parse_tokenizer_config("lowercase,split_by_space")
        )
        tokens = tokenizer(text)
        self.assertIn("hello", tokens)
        self.assertIn("world,", tokens)
        self.assertIn("stop", tokens)
        self.assertIn("this!", tokens)

    def test_tokenizer_invalid_toggle_raises(self):
        with self.assertRaises(ValueError):
            _parse_tokenizer_config("lowercase,unknown_toggle,split")

    def test_tokenizer_lowercase_toggle(self):
        tokenizer = _build_tokenizer(
            _parse_tokenizer_config("lowercase,split_by_space")
        )
        tokens = tokenizer("HELLO World")
        self.assertEqual(set(tokens), {"hello", "world"})

    def test_tokenizer_no_lowercase(self):
        tokenizer = _build_tokenizer(_parse_tokenizer_config("split_by_space"))
        tokens = tokenizer("HELLO world")
        self.assertIn("HELLO", tokens)
        self.assertIn("world", tokens)

    def test_tokenizer_missing_split_by_space_raises(self):
        with self.assertRaises(ValueError):
            _build_tokenizer(["lowercase"])

    def test_tokenizer_strip_punctuation(self):
        tokenizer = _build_tokenizer(
            _parse_tokenizer_config("strip_punctuation,split_by_space")
        )
        tokens = tokenizer("hello, world! test.")
        self.assertIn("hello", tokens)
        self.assertIn("world", tokens)

    def test_tokenizer_remove_stopword(self):
        tokenizer = _build_tokenizer(
            _parse_tokenizer_config("lowercase,split_by_space,remove_stopword")
        )
        tokens = tokenizer("the quick brown fox jumps over the lazy dog")
        self.assertNotIn("the", tokens)
        self.assertIn("quick", tokens)


class TestBuildIndex(unittest.TestCase):
    """Pure build_index() tests — no file I/O."""

    def test_build_index_with_small_corpus(self):
        lf = _make_keywords_lf(
            [
                (1, 101, "stress", 5),
                (2, 101, "anxiety", 3),
                (3, 102, "resilience", 4),
                (4, 103, "coping", 2),
            ]
        )
        result = build_index(lf)
        self.assertEqual(len(result["corpus"]), 3)
        self.assertIn(101, result["entity_map"])
        self.assertIn(102, result["entity_map"])
        self.assertIn(103, result["entity_map"])
        self.assertIsNotNone(result["bm25_object"])

    def test_build_index_with_empty_corpus(self):
        lf = _make_keywords_lf([])
        result = build_index(lf)
        self.assertEqual(len(result["corpus"]), 0)
        self.assertEqual(len(result["entity_map"]), 0)
        self.assertIsNone(result["bm25_object"])

    def test_metadata_contains_required_fields(self):
        lf = _make_keywords_lf([(1, 1, "kw", 1)])
        result = build_index(lf)
        meta = result["metadata"]
        self.assertIn("corpus_size", meta)
        self.assertIn("exemplar_count", meta)
        self.assertIn("tokenizer_config", meta)
        self.assertIn("corpus_hash", meta)
        self.assertEqual(meta["corpus_size"], 1)
        self.assertEqual(meta["exemplar_count"], 1)


class TestGetScores(unittest.TestCase):
    """Pure get_scores() tests — receives index as parameter."""

    def setUp(self):
        self.index = build_index(
            _make_keywords_lf(
                [
                    (1, 1, "apple", 1),
                    (2, 2, "banana", 1),
                    (3, 3, "cherry", 1),
                ]
            )
        )

    def test_scores_normalized_range(self):
        scores = get_scores("fruit apple banana", self.index)
        for score in scores.values():
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)

    def test_all_equal_returns_zeros(self):
        scores = get_scores("nonexistent keyword", self.index)
        for score in scores.values():
            self.assertEqual(score, 0.0)

    def test_get_top_n_returns_sorted_limited(self):
        top3 = get_top_n("apple", self.index, n=3)
        self.assertEqual(len(top3), 3)
        score_vals = [s for _, s in top3]
        self.assertEqual(score_vals, sorted(score_vals, reverse=True))

    def test_get_index_info_returns_metadata(self):
        info = get_index_info(self.index)
        self.assertIn("corpus_size", info)
        self.assertIn("exemplar_count", info)
        self.assertIn("tokenizer_config", info)
        self.assertEqual(info["corpus_size"], 3)

    def test_empty_index_scores(self):
        empty_idx = build_index(_make_keywords_lf([]))
        scores = get_scores("anything", empty_idx)
        self.assertEqual(scores, {})

    def test_top_n_empty_index(self):
        empty_idx = build_index(_make_keywords_lf([]))
        top = get_top_n("anything", empty_idx, n=5)
        self.assertEqual(top, [])


if __name__ == "__main__":
    unittest.main()
