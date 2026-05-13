"""Comprehensive tests for sentence-transformer embedding module.

Covers:
- generate_embedding shape/dtype and L2 normalization
- Deterministic output for identical inputs
- Model hash consistency with hash_utils
- Thread safety under concurrent access
- Cache management: reload_model, clear_model_cache
"""

# flake8: noqa: E402
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import numpy as np  # noqa: E402
from persistence.hash_utils import compute_model_hash  # noqa: E402
from semantic.embeddings import (  # noqa: E402
    EMBEDDING_DIM,
    MODEL_NAME,
    EmbeddingError,
    _get_model_cache_subdir,
    clear_model_cache,
    generate_embedding,
    get_model_hash,
    reload_model,
)

_TEST_TEXT = (
    "Climate resilience requires adaptive capacity and "
    "community-based resource management strategies."
)


class TestEmbeddingsCore(unittest.TestCase):
    """Core embedding functionality with real model (loaded once per session)."""

    @classmethod
    def setUpClass(cls):
        cls.embedding = generate_embedding(_TEST_TEXT)

    def test_shape_and_dtype(self):
        emb = self.embedding
        self.assertEqual(emb.shape, (EMBEDDING_DIM,))
        self.assertEqual(emb.dtype, np.float32)

    def test_l2_normalized(self):
        emb = self.embedding
        norm = np.linalg.norm(emb)
        self.assertAlmostEqual(norm, 1.0, places=6)

    def test_zero_length_text_does_not_crash(self):
        emb = generate_embedding("")
        self.assertEqual(emb.shape, (EMBEDDING_DIM,))
        self.assertEqual(emb.dtype, np.float32)
        norm = np.linalg.norm(emb)
        self.assertAlmostEqual(norm, 1.0, places=6)

    def test_deterministic_output(self):
        text = "Consistent input produces consistent embeddings."
        emb1 = generate_embedding(text)
        emb2 = generate_embedding(text)
        np.testing.assert_array_almost_equal(emb1, emb2)

    def test_different_texts_different_embeddings(self):
        emb_a = generate_embedding("Apple")
        emb_b = generate_embedding("Banana")
        similarity = float(np.dot(emb_a, emb_b))
        self.assertLess(
            similarity,
            0.99,
            f"Expected cosine < 0.99, got {similarity}",
        )

    def test_model_hash_consistency(self):
        expected = compute_model_hash(MODEL_NAME)
        actual = get_model_hash()
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 16)

    def test_thread_safety(self):
        texts = [f"Thread safety test {i}" for i in range(10)]
        results = [None] * 10
        errors = [None] * 10

        def _encode(idx: int):
            try:
                results[idx] = generate_embedding(texts[idx])
            except Exception as e:
                errors[idx] = e

        threads = [threading.Thread(target=_encode, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        for i, err in enumerate(errors):
            self.assertIsNone(err, f"Thread {i} failed: {err}")
        for i, emb in enumerate(results):
            self.assertEqual(
                emb.shape,
                (EMBEDDING_DIM,),
                f"Thread {i} produced wrong shape",
            )
            self.assertAlmostEqual(
                np.linalg.norm(emb),
                1.0,
                places=6,
                msg=f"Thread {i} not normalized",
            )


class TestEmbeddingCacheManagement(unittest.TestCase):
    """Cache management tests using a temporary cache directory.

    Avoids re-downloading by manually creating the expected cache subdirectory
    structure rather than triggering actual model loads into the temp dir.
    """

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.temp_cache = self.temp_dir / "cache"
        self.temp_cache.mkdir(parents=True, exist_ok=True)
        import semantic.embeddings as _emb_mod

        self.emb_mod = _emb_mod
        self.orig_cache = _emb_mod.MODEL_CACHE_DIR

    def tearDown(self):
        self.emb_mod.MODEL_CACHE_DIR = self.orig_cache
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_reload_model_resets_singleton(self):
        generate_embedding("warmup")
        self.assertIsNotNone(self.emb_mod._model)
        self.assertIsNotNone(self.emb_mod._model_hash)
        reload_model()
        self.assertIsNone(self.emb_mod._model)
        self.assertIsNone(self.emb_mod._model_hash)

    def test_clear_model_cache_removes_disk_cache(self):
        cache_subdir = self.temp_cache / f"models--{MODEL_NAME.replace('/', '--')}"
        cache_subdir.mkdir(parents=True, exist_ok=True)
        (cache_subdir / "snapshots").mkdir(exist_ok=True)
        (cache_subdir / "blobs").mkdir(exist_ok=True)
        self.emb_mod.MODEL_CACHE_DIR = self.temp_cache
        self.assertTrue(cache_subdir.exists())
        clear_model_cache()
        self.assertFalse(cache_subdir.exists())
        self.assertIsNone(self.emb_mod._model)
        self.assertIsNone(self.emb_mod._model_hash)

    def test_clear_model_cache_noop_when_not_cached(self):
        self.emb_mod.MODEL_CACHE_DIR = self.temp_cache
        cache_subdir = _get_model_cache_subdir()
        self.assertFalse(cache_subdir.exists())
        clear_model_cache()
        self.assertFalse(cache_subdir.exists())

    def test_reload_model_without_clear_keeps_disk_cache(self):
        generate_embedding("warmup")
        cache_subdir = _get_model_cache_subdir()
        self.assertTrue(
            cache_subdir.exists(),
            "Cache should exist after model load",
        )
        reload_model(clear_cache=False)
        self.assertTrue(
            cache_subdir.exists(),
            "Cache should persist after reload without clear_cache",
        )
        self.assertIsNone(self.emb_mod._model)
        self.assertIsNone(self.emb_mod._model_hash)


class TestEmbeddingExceptions(unittest.TestCase):
    """Error handling edge cases."""

    def test_embedding_error_is_exception(self):
        self.assertTrue(issubclass(EmbeddingError, Exception))

    def test_generate_embedding_invalid_type_raises(self):
        with self.assertRaises(Exception):
            generate_embedding(123)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
