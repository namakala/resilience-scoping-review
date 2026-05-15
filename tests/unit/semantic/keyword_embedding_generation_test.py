"""Comprehensive tests for keyword embedding generation.

Covers:
- Full generation flow (happy path): all new, all cached, mixed stale
- Cache hit verification: content_hash match skips encoding
- Content_hash mismatch triggers regeneration
- Model hash mismatch triggers regeneration
- Empty keywords list (no-op)
- Batch boundary handling
- Entity ID format verification
- Return dict structure and types
"""

# flake8: noqa: E402
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402
sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import numpy as np
import polars as pl
from conftest import autopatch
from persistence.duckdb_init import initialize_database
from persistence.embedding_cache import put_embedding
from persistence.loaders import clear_cache

_MODEL_HASH = "test_model_hash_001"


def _fake_embeddings(texts, batch_size=32):
    """Return a (N, 384) float32 array for any input batch."""
    return np.random.rand(len(texts), 384).astype("float32")


def _make_keyword_df(exemplar_keywords: dict[int, list[str]]) -> pl.LazyFrame:
    """Create a LazyFrame from a mapping of exemplar_id -> keyword list."""
    rows = []
    kw_id = 0
    for eid, kws in exemplar_keywords.items():
        for kw in kws:
            kw_id += 1
            rows.append(
                {
                    "keyword_id": kw_id,
                    "exemplar_id": eid,
                    "keyword_text": kw,
                    "frequency": len(kws) * 1000,
                }
            )
    return pl.DataFrame(
        rows,
        schema={
            "keyword_id": pl.Int64,
            "exemplar_id": pl.Int64,
            "keyword_text": pl.String,
            "frequency": pl.Int32,
        },
    ).lazy()


def _compute_content_hash(text: str) -> str:
    """Compute keyword content_hash the same way as production code."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class TestKeywordEmbeddingGeneration(unittest.TestCase):
    """Tests for generate_keyword_embeddings with real DuckDB + mocks."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_kw_embed.duckdb"
        initialize_database(db_path=self.db_path)
        import duckdb as _duckdb

        self.con = _duckdb.connect(str(self.db_path))
        clear_cache()

    def tearDown(self):
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        clear_cache()

    # -- All-new keywords -----------------------------------------------------

    @autopatch("semantic.keyword_embedding.load_keywords")
    @autopatch("semantic.embedding_generation.generate_embeddings")
    @autopatch("semantic.keyword_embedding.get_model_hash")
    def test_all_new_keywords(self, mock_get_hash, mock_gen_embs, mock_load):
        """Three exemplars × 3 keywords = 9 keyword embeddings."""
        mock_get_hash.return_value = _MODEL_HASH
        mock_load.return_value = _make_keyword_df(
            {
                1: ["resilience", "adaptation", "coping"],
                2: ["stress", "burnout", "recovery"],
                3: ["support", "community", "network"],
            }
        )
        mock_gen_embs.side_effect = _fake_embeddings

        from semantic.keyword_embedding import generate_keyword_embeddings

        result = generate_keyword_embeddings(self.con, batch_size=4)

        self.assertEqual(result["total"], 9)
        self.assertEqual(result["generated"], 9)
        self.assertEqual(result["cached"], 0)

        count = self.con.execute(
            "SELECT COUNT(*) FROM embedding_cache WHERE entity_type = 'keyword'"
        ).fetchone()[0]
        self.assertEqual(count, 9)

    # -- All cached (skip encoding) ------------------------------------------

    @autopatch("semantic.keyword_embedding.load_keywords")
    @autopatch("semantic.embedding_generation.generate_embeddings")
    @autopatch("semantic.keyword_embedding.get_model_hash")
    def test_all_cached_skip_encoding(self, mock_get_hash, mock_gen_embs, mock_load):
        """Nine keywords already in cache: all skip encoding."""
        mock_get_hash.return_value = _MODEL_HASH
        lf = _make_keyword_df(
            {
                1: ["resilience", "adaptation", "coping"],
                2: ["stress", "burnout", "recovery"],
                3: ["support", "community", "network"],
            }
        )
        mock_load.return_value = lf

        # Pre-populate cache with correct content_hash
        idx = 0
        current_eid = None
        for row in (
            lf.collect()
            .sort(["exemplar_id", "frequency"], descending=[False, True])
            .iter_rows(named=True)
        ):
            eid = row["exemplar_id"]
            if eid != current_eid:
                current_eid = eid
                idx = 0
            entity_id = f"{eid}_kw_{idx}"
            ch = _compute_content_hash(row["keyword_text"])
            put_embedding(
                self.con,
                entity_id,
                "keyword",
                np.random.rand(384).astype("float32"),
                _MODEL_HASH,
                ch,
            )
            idx += 1

        from semantic.keyword_embedding import generate_keyword_embeddings

        result = generate_keyword_embeddings(self.con)

        self.assertEqual(result["total"], 9)
        self.assertEqual(result["generated"], 0)
        self.assertEqual(result["cached"], 9)
        mock_gen_embs.assert_not_called()

    # -- Mixed stale / cached -------------------------------------------------

    @autopatch("semantic.keyword_embedding.load_keywords")
    @autopatch("semantic.embedding_generation.generate_embeddings")
    @autopatch("semantic.keyword_embedding.get_model_hash")
    def test_some_stale_content_hash(self, mock_get_hash, mock_gen_embs, mock_load):
        """Two keywords cached valid, one stale -> only one regenerated."""
        mock_get_hash.return_value = _MODEL_HASH
        # One exemplar, 3 keywords: first two cached with correct hash,
        # third cached with stale hash
        lf = _make_keyword_df({1: ["resilience", "adaptation", "coping"]})
        mock_load.return_value = lf
        mock_gen_embs.side_effect = _fake_embeddings

        # Cache keyword 0 and 1 with correct content_hash
        for idx, kw_text in enumerate(["resilience", "adaptation"]):
            ch = _compute_content_hash(kw_text)
            put_embedding(
                self.con,
                f"1_kw_{idx}",
                "keyword",
                np.random.rand(384).astype("float32"),
                _MODEL_HASH,
                ch,
            )

        # Cache keyword 2 with STALE content_hash
        put_embedding(
            self.con,
            "1_kw_2",
            "keyword",
            np.random.rand(384).astype("float32"),
            _MODEL_HASH,
            "stale_hash_abc",
        )

        from semantic.keyword_embedding import generate_keyword_embeddings

        result = generate_keyword_embeddings(self.con)

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["generated"], 1)
        self.assertEqual(result["cached"], 2)

    # -- Empty keywords (no-op) ------------------------------------------------

    @autopatch("semantic.keyword_embedding.load_keywords")
    @autopatch("semantic.embedding_generation.generate_embeddings")
    @autopatch("semantic.keyword_embedding.get_model_hash")
    def test_empty_keywords(self, mock_get_hash, mock_gen_embs, mock_load):
        """No keywords returns zero counts and skips all work."""
        empty = pl.DataFrame(
            schema={
                "keyword_id": pl.Int64,
                "exemplar_id": pl.Int64,
                "keyword_text": pl.String,
                "frequency": pl.Int32,
            }
        )
        mock_load.return_value = empty.lazy()

        from semantic.keyword_embedding import generate_keyword_embeddings

        result = generate_keyword_embeddings(self.con)

        self.assertEqual(result["total"], 0)
        self.assertEqual(result["generated"], 0)
        self.assertEqual(result["cached"], 0)
        self.assertEqual(result["duration_seconds"], 0.0)
        mock_gen_embs.assert_not_called()
        mock_get_hash.assert_not_called()

    # -- Model hash mismatch --------------------------------------------------

    @autopatch("semantic.keyword_embedding.load_keywords")
    @autopatch("semantic.embedding_generation.generate_embeddings")
    @autopatch("semantic.keyword_embedding.get_model_hash")
    def test_model_hash_mismatch(self, mock_get_hash, mock_gen_embs, mock_load):
        """Cache entries with different model_hash are treated as misses."""
        mock_get_hash.return_value = "new_model_hash_v2"
        lf = _make_keyword_df({1: ["resilience", "adaptation"]})
        mock_load.return_value = lf
        mock_gen_embs.side_effect = _fake_embeddings

        # Pre-populate with OLD model_hash
        for idx, kw_text in enumerate(["resilience", "adaptation"]):
            ch = _compute_content_hash(kw_text)
            put_embedding(
                self.con,
                f"1_kw_{idx}",
                "keyword",
                np.random.rand(384).astype("float32"),
                "old_model_hash_v1",
                ch,
            )

        from semantic.keyword_embedding import generate_keyword_embeddings

        result = generate_keyword_embeddings(self.con)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["generated"], 2)
        self.assertEqual(result["cached"], 0)

    # -- Return dict structure ------------------------------------------------

    @autopatch("semantic.keyword_embedding.load_keywords")
    @autopatch("semantic.embedding_generation.generate_embeddings")
    @autopatch("semantic.keyword_embedding.get_model_hash")
    def test_stats_dict_structure(self, mock_get_hash, mock_gen_embs, mock_load):
        """Return dict contains all expected keys with correct types."""
        mock_get_hash.return_value = _MODEL_HASH
        mock_load.return_value = _make_keyword_df({1: ["resilience"]})
        mock_gen_embs.side_effect = _fake_embeddings

        from semantic.keyword_embedding import generate_keyword_embeddings

        result = generate_keyword_embeddings(self.con)

        self.assertIn("total", result)
        self.assertIn("cached", result)
        self.assertIn("generated", result)
        self.assertIn("duration_seconds", result)
        self.assertIsInstance(result["total"], int)
        self.assertIsInstance(result["cached"], int)
        self.assertIsInstance(result["generated"], int)
        self.assertIsInstance(result["duration_seconds"], float)

    # -- Entity ID format ----------------------------------------------------

    @autopatch("semantic.keyword_embedding.load_keywords")
    @autopatch("semantic.embedding_generation.generate_embeddings")
    @autopatch("semantic.keyword_embedding.get_model_hash")
    def test_entity_id_format(self, mock_get_hash, mock_gen_embs, mock_load):
        """Entity IDs follow f\"{eid}_kw_{i}\" pattern."""
        mock_get_hash.return_value = _MODEL_HASH
        # 2 exemplars, 2 keywords each
        mock_load.return_value = _make_keyword_df(
            {
                10: ["kw_a", "kw_b"],
                20: ["kw_c", "kw_d"],
            }
        )
        mock_gen_embs.side_effect = _fake_embeddings

        from semantic.keyword_embedding import generate_keyword_embeddings

        generate_keyword_embeddings(self.con, batch_size=2)

        ids = {
            r[0]
            for r in self.con.execute(
                "SELECT entity_id FROM embedding_cache WHERE entity_type = 'keyword'"
            ).fetchall()
        }
        self.assertIn("10_kw_0", ids)
        self.assertIn("10_kw_1", ids)
        self.assertIn("20_kw_0", ids)
        self.assertIn("20_kw_1", ids)

    # -- Batch boundary ------------------------------------------------------

    @autopatch("semantic.keyword_embedding.load_keywords")
    @autopatch("semantic.embedding_generation.generate_embeddings")
    @autopatch("semantic.keyword_embedding.get_model_hash")
    def test_batch_boundary(self, mock_get_hash, mock_gen_embs, mock_load):
        """Five keywords with batch_size=2 produce three encode calls."""
        mock_get_hash.return_value = _MODEL_HASH
        mock_load.return_value = _make_keyword_df(
            {
                1: ["a", "b", "c"],
                2: ["d", "e"],
            }
        )
        mock_gen_embs.side_effect = _fake_embeddings

        from semantic.keyword_embedding import generate_keyword_embeddings

        result = generate_keyword_embeddings(self.con, batch_size=2)

        self.assertEqual(result["total"], 5)
        self.assertEqual(result["generated"], 5)
        self.assertEqual(mock_gen_embs.call_count, 3)

        call_sizes = [len(args[0][0]) for args in mock_gen_embs.call_args_list]
        self.assertEqual(call_sizes, [2, 2, 1])

    # -- Cache hit on second run ---------------------------------------------

    @autopatch("semantic.keyword_embedding.load_keywords")
    @autopatch("semantic.embedding_generation.generate_embeddings")
    @autopatch("semantic.keyword_embedding.get_model_hash")
    def test_cache_hit_second_run(self, mock_get_hash, mock_gen_embs, mock_load):
        """Second call uses cache; generate_embeddings called only once."""
        mock_get_hash.return_value = _MODEL_HASH
        mock_load.return_value = _make_keyword_df({1: ["resilience"]})
        mock_gen_embs.side_effect = _fake_embeddings

        from semantic.keyword_embedding import generate_keyword_embeddings

        # First run: generate
        result1 = generate_keyword_embeddings(self.con)
        self.assertEqual(result1["generated"], 1)

        # Second run: all cached
        result2 = generate_keyword_embeddings(self.con)
        self.assertEqual(result2["generated"], 0)
        self.assertEqual(result2["cached"], 1)

        # generate_embeddings should have been called only once
        self.assertEqual(mock_gen_embs.call_count, 1)


if __name__ == "__main__":
    unittest.main()
