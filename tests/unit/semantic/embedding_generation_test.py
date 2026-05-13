"""Comprehensive tests for exemplar embedding generation.

Covers:
- Full generation flow (happy path): all new, all cached, mixed stale
- Cache hit verification: content_hash match skips encoding
- Content_hash mismatch triggers regeneration
- Model hash mismatch triggers regeneration
- Empty exemplar set (no-op)
- Batch boundary handling: batch_size partitioning
- Return dict structure and types
"""

# flake8: noqa: E402
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import numpy as np  # noqa: E402
import polars as pl  # noqa: E402
from persistence.duckdb_init import initialize_database  # noqa: E402
from persistence.embedding_cache import put_embedding  # noqa: E402
from persistence.loaders import clear_cache  # noqa: E402
from semantic.embedding_generation import generate_exemplar_embeddings  # noqa: E402

_MODEL_HASH = "test_model_hash_001"


def _fake_embeddings(texts, batch_size=32):
    """Return a (N, 384) float32 array for any input batch."""
    return np.random.rand(len(texts), 384).astype("float32")


def _make_exemplar_df(n: int, seed: int = 0) -> pl.LazyFrame:
    """Create a LazyFrame with n exemplars for testing."""
    rng = np.random.default_rng(seed)
    data = {
        "id": list(range(1, n + 1)),
        "content": [f"exemplar content {i}" for i in range(1, n + 1)],
        "content_hash": [f"ch_{i}_{rng.integers(0, 99999)}" for i in range(1, n + 1)],
    }
    return pl.DataFrame(data).lazy()


class TestExemplarEmbeddingGeneration(unittest.TestCase):
    """Tests for generate_exemplar_embeddings with real DuckDB + mocks."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_embed_gen.duckdb"
        initialize_database(db_path=self.db_path)
        import duckdb as _duckdb

        self.con = _duckdb.connect(str(self.db_path))
        clear_cache()

    def tearDown(self):
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        clear_cache()

    # -- All-new exemplars ---------------------------------------------------

    @mock.patch("semantic.embedding_generation.load_exemplars")
    @mock.patch("semantic.embedding_generation.generate_embeddings")
    @mock.patch("semantic.embedding_generation.get_model_hash")
    def test_all_new_exemplars(self, mock_get_hash, mock_gen_embs, mock_load):
        """Three exemplars with empty cache: all three are generated."""
        mock_get_hash.return_value = _MODEL_HASH
        mock_load.return_value = _make_exemplar_df(3, seed=1)
        mock_gen_embs.side_effect = _fake_embeddings

        result = generate_exemplar_embeddings(self.con, batch_size=2)

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["generated"], 3)
        self.assertEqual(result["cached"], 0)

        count = self.con.execute(
            "SELECT COUNT(*) FROM embedding_cache " "WHERE entity_type = 'exemplar'"
        ).fetchone()[0]
        self.assertEqual(count, 3)

    # -- All cached (skip encoding) ------------------------------------------

    @mock.patch("semantic.embedding_generation.load_exemplars")
    @mock.patch("semantic.embedding_generation.generate_embeddings")
    @mock.patch("semantic.embedding_generation.get_model_hash")
    def test_all_cached_skip_encoding(self, mock_get_hash, mock_gen_embs, mock_load):
        """Three exemplars already in cache: all skip encoding."""
        mock_get_hash.return_value = _MODEL_HASH
        lf = _make_exemplar_df(3, seed=2)
        mock_load.return_value = lf
        df = lf.collect()

        for row in df.iter_rows(named=True):
            emb = np.random.rand(384).astype("float32")
            put_embedding(
                self.con,
                str(row["id"]),
                "exemplar",
                emb,
                _MODEL_HASH,
                row["content_hash"],
            )

        result = generate_exemplar_embeddings(self.con)

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["generated"], 0)
        self.assertEqual(result["cached"], 3)
        mock_gen_embs.assert_not_called()

    # -- Mixed stale / cached ------------------------------------------------

    @mock.patch("semantic.embedding_generation.load_exemplars")
    @mock.patch("semantic.embedding_generation.generate_embeddings")
    @mock.patch("semantic.embedding_generation.get_model_hash")
    def test_some_stale_content_hash(self, mock_get_hash, mock_gen_embs, mock_load):
        """Three exemplars: one cached valid, two with stale content_hash."""
        mock_get_hash.return_value = _MODEL_HASH
        lf = _make_exemplar_df(3, seed=3)
        mock_load.return_value = lf
        df = lf.collect()
        mock_gen_embs.side_effect = _fake_embeddings

        # Cache exemplar 1 with the correct (current) content_hash
        row1 = df.row(0, named=True)
        put_embedding(
            self.con,
            str(row1["id"]),
            "exemplar",
            np.random.rand(384).astype("float32"),
            _MODEL_HASH,
            row1["content_hash"],
        )

        # Cache exemplars 2, 3 with STALE content_hash
        for idx in [1, 2]:
            row = df.row(idx, named=True)
            put_embedding(
                self.con,
                str(row["id"]),
                "exemplar",
                np.random.rand(384).astype("float32"),
                _MODEL_HASH,
                "stale_" + row["content_hash"],
            )

        result = generate_exemplar_embeddings(self.con)

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["generated"], 2)
        self.assertEqual(result["cached"], 1)

    # -- Empty exemplars (no-op) ---------------------------------------------

    @mock.patch("semantic.embedding_generation.load_exemplars")
    @mock.patch("semantic.embedding_generation.generate_embeddings")
    @mock.patch("semantic.embedding_generation.get_model_hash")
    def test_empty_exemplars(self, mock_get_hash, mock_gen_embs, mock_load):
        """No exemplars returns zero counts and skips all work."""
        mock_load.return_value = pl.DataFrame(
            schema={
                "id": pl.Int64,
                "content": pl.String,
                "content_hash": pl.String,
            }
        ).lazy()

        result = generate_exemplar_embeddings(self.con)

        self.assertEqual(result["total"], 0)
        self.assertEqual(result["generated"], 0)
        self.assertEqual(result["cached"], 0)
        self.assertEqual(result["duration_seconds"], 0.0)
        mock_gen_embs.assert_not_called()
        mock_get_hash.assert_not_called()

    # -- Model hash mismatch forces regeneration -----------------------------

    @mock.patch("semantic.embedding_generation.load_exemplars")
    @mock.patch("semantic.embedding_generation.generate_embeddings")
    @mock.patch("semantic.embedding_generation.get_model_hash")
    def test_model_hash_mismatch(self, mock_get_hash, mock_gen_embs, mock_load):
        """Cache entries with different model_hash are treated as misses."""
        mock_get_hash.return_value = "new_model_hash_v2"
        lf = _make_exemplar_df(2, seed=4)
        mock_load.return_value = lf
        df = lf.collect()
        mock_gen_embs.side_effect = _fake_embeddings

        # Pre-populate with OLD model_hash
        for row in df.iter_rows(named=True):
            put_embedding(
                self.con,
                str(row["id"]),
                "exemplar",
                np.random.rand(384).astype("float32"),
                "old_model_hash_v1",
                row["content_hash"],
            )

        result = generate_exemplar_embeddings(self.con)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["generated"], 2)
        self.assertEqual(result["cached"], 0)

    # -- Return dict structure -----------------------------------------------

    @mock.patch("semantic.embedding_generation.load_exemplars")
    @mock.patch("semantic.embedding_generation.generate_embeddings")
    @mock.patch("semantic.embedding_generation.get_model_hash")
    def test_stats_dict_structure(self, mock_get_hash, mock_gen_embs, mock_load):
        """Return dict contains all expected keys with correct types."""
        mock_get_hash.return_value = _MODEL_HASH
        mock_load.return_value = _make_exemplar_df(1, seed=5)
        mock_gen_embs.side_effect = _fake_embeddings

        result = generate_exemplar_embeddings(self.con)

        self.assertIn("total", result)
        self.assertIn("cached", result)
        self.assertIn("generated", result)
        self.assertIn("duration_seconds", result)
        self.assertIsInstance(result["total"], int)
        self.assertIsInstance(result["cached"], int)
        self.assertIsInstance(result["generated"], int)
        self.assertIsInstance(result["duration_seconds"], float)

    # -- Batch boundary ------------------------------------------------------

    @mock.patch("semantic.embedding_generation.load_exemplars")
    @mock.patch("semantic.embedding_generation.generate_embeddings")
    @mock.patch("semantic.embedding_generation.get_model_hash")
    def test_batch_boundary(self, mock_get_hash, mock_gen_embs, mock_load):
        """Five exemplars with batch_size=2 produce three encode calls."""
        mock_get_hash.return_value = _MODEL_HASH
        mock_load.return_value = _make_exemplar_df(5, seed=6)
        mock_gen_embs.side_effect = _fake_embeddings

        result = generate_exemplar_embeddings(self.con, batch_size=2)

        self.assertEqual(result["total"], 5)
        self.assertEqual(result["generated"], 5)
        self.assertEqual(mock_gen_embs.call_count, 3)

        call_sizes = [len(args[0][0]) for args in mock_gen_embs.call_args_list]
        self.assertEqual(call_sizes, [2, 2, 1])


if __name__ == "__main__":
    unittest.main()
