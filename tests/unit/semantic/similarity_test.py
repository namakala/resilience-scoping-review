"""Comprehensive unit tests for embedding similarity computation.

Covers:
- Known vectors produce exact expected cosine values
- Single entity returns 1x1 matrix with 1.0
- Diagonal entries are exactly 1.0
- Matrix is symmetric (A == A.T)
- Output dtype is float32
- Cache miss raises CacheMissError
- Empty list returns 0x0 matrix
- Values are in [-1, 1]
"""

# flake8: noqa: E402
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import duckdb
import numpy as np
from persistence.duckdb_init import initialize_database
from persistence.embedding_cache import put_embedding
from semantic.exceptions import CacheMissError
from semantic.similarity import compute_similarity


def _put_embedding_simple(
    con: duckdb.DuckDBPyConnection,
    entity_id: int,
    entity_type: str,
    vector: np.ndarray,
) -> None:
    """Insert an embedding with dummy model_hash and content_hash."""
    put_embedding(
        con, str(entity_id), entity_type, vector, "test_model_hash", "test_content_hash"
    )


class TestSimilarityComputation(unittest.TestCase):
    """Tests for compute_similarity using DuckDB-backed embedding_cache."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_similarity.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))

    def tearDown(self):
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_known_vectors(self):
        """Orthonormal vectors produce exact cosine values."""
        # Three 4-d unit vectors:
        # v1 = [1, 0, 0, 0]
        # v2 = [0, 1, 0, 0]
        # v3 = [0.6, 0.8, 0, 0]
        v1 = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
        v2 = np.array([0.0, 1.0, 0.0, 0.0], dtype="float32")
        v3 = np.array([0.6, 0.8, 0.0, 0.0], dtype="float32")

        _put_embedding_simple(self.con, 1, "code", v1)
        _put_embedding_simple(self.con, 2, "code", v2)
        _put_embedding_simple(self.con, 3, "code", v3)

        sim = compute_similarity([1, 2, 3], "code", self.con)

        self.assertEqual(sim.shape, (3, 3))
        self.assertEqual(sim.dtype, np.float32)

        # Diagonal
        self.assertAlmostEqual(sim[0, 0], 1.0, places=6)
        self.assertAlmostEqual(sim[1, 1], 1.0, places=6)
        self.assertAlmostEqual(sim[2, 2], 1.0, places=6)

        # v1·v2 = 0
        self.assertAlmostEqual(sim[0, 1], 0.0, places=6)
        self.assertAlmostEqual(sim[1, 0], 0.0, places=6)

        # v1·v3 = 0.6
        self.assertAlmostEqual(sim[0, 2], 0.6, places=6)
        self.assertAlmostEqual(sim[2, 0], 0.6, places=6)

        # v2·v3 = 0.8
        self.assertAlmostEqual(sim[1, 2], 0.8, places=6)
        self.assertAlmostEqual(sim[2, 1], 0.8, places=6)

    def test_single_entity(self):
        """Single entity returns 1x1 matrix with value 1.0."""
        v = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
        _put_embedding_simple(self.con, 42, "theme", v)

        sim = compute_similarity([42], "theme", self.con)

        self.assertEqual(sim.shape, (1, 1))
        self.assertEqual(sim.dtype, np.float32)
        self.assertAlmostEqual(sim[0, 0], 1.0, places=6)

    def test_diagonal_is_one(self):
        """All diagonal entries are exactly 1.0."""
        np.random.seed(0)
        vectors = []
        for i in range(5):
            v = np.random.rand(384).astype("float32")
            v = v / np.linalg.norm(v)
            vectors.append(v)
            _put_embedding_simple(self.con, i + 1, "exemplar", v)

        sim = compute_similarity([1, 2, 3, 4, 5], "exemplar", self.con)

        for i in range(5):
            self.assertEqual(
                sim[i, i],
                1.0,
                f"Diagonal entry [{i},{i}] is {sim[i,i]}, expected 1.0",
            )

    def test_symmetric(self):
        """Similarity matrix equals its transpose."""
        np.random.seed(1)
        for i in range(4):
            v = np.random.rand(384).astype("float32")
            v = v / np.linalg.norm(v)
            _put_embedding_simple(self.con, i + 10, "code", v)

        sim = compute_similarity([10, 11, 12, 13], "code", self.con)
        np.testing.assert_allclose(sim, sim.T, atol=1e-6)

    def test_float32_dtype(self):
        """Output dtype is always float32."""
        v = np.array([1.0, 0.0], dtype="float32")
        _put_embedding_simple(self.con, 99, "interpretation", v)

        sim = compute_similarity([99], "interpretation", self.con)
        self.assertEqual(sim.dtype, np.float32)

    def test_cache_miss_raises(self):
        """Missing entity raises CacheMissError."""
        v = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
        _put_embedding_simple(self.con, 1, "code", v)
        # ID 2 is not in cache

        with self.assertRaises(CacheMissError):
            compute_similarity([1, 2], "code", self.con)

    def test_empty_list(self):
        """Empty entity list returns 0x0 matrix."""
        sim = compute_similarity([], "code", self.con)
        self.assertEqual(sim.shape, (0, 0))
        self.assertEqual(sim.dtype, np.float32)

    def test_values_in_range(self):
        """All similarity values are in [-1, 1]."""
        np.random.seed(2)
        for i in range(6):
            v = np.random.rand(384).astype("float32")
            v = v / np.linalg.norm(v)
            _put_embedding_simple(self.con, i + 100, "code", v)

        sim = compute_similarity([100, 101, 102, 103, 104, 105], "code", self.con)
        self.assertTrue(np.all(sim >= -1.0 - 1e-6))
        self.assertTrue(np.all(sim <= 1.0 + 1e-6))


if __name__ == "__main__":
    unittest.main()
