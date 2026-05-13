"""Comprehensive unit tests for neighbor discovery service.

Covers:
- Known vectors produce expected neighbor rankings
- Self entity excluded from results
- Similarity threshold (>= 0.5) filters correctly
- k defaults, configurability, clamping
- Fewer than k eligible candidates handled gracefully
- Empty scope, missing entity, missing embedding
- In-memory TTL cache: hit, expiry, explicit clear
- Results sorted descending by score (ties by ID)
"""

# flake8: noqa: E402
import sys
import tempfile
import time as time_module
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import duckdb
import numpy as np
from persistence.duckdb_init import initialize_database
from persistence.embedding_cache import put_embedding
from semantic.neighbors import _CACHE, _CACHE_TTL, clear_neighbor_cache, find_neighbors


def _put_embedding_simple(
    con: duckdb.DuckDBPyConnection,
    entity_id: int,
    entity_type: str,
    vector: np.ndarray,
) -> None:
    """Insert an embedding with dummy model_hash and content_hash."""
    put_embedding(
        con,
        str(entity_id),
        entity_type,
        vector,
        "test_model_hash",
        "test_content_hash",
    )


def _insert_node(
    con: duckdb.DuckDBPyConnection,
    entity_id: int,
    entity_type: str,
    tag: str = "Test.Tag",
) -> None:
    """Insert a minimal node row so find_neighbors can look up its tag."""
    con.execute(
        "INSERT INTO nodes (id, type, name, definition, tag, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [entity_id, entity_type, f"n{entity_id}", "test", tag, "draft"],
    )


class TestFindNeighbors(unittest.TestCase):
    """Tests for find_neighbors using DuckDB-backed node/embedding
    storage, with resolve_candidate_ids mocked for isolation."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_neighbors.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))

    def tearDown(self):
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)
        _CACHE.clear()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _setup_vectors_5(self):
        """Create 5 unit vectors in 4D plus nodes + embeddings.

        v1 = [1, 0, 0, 0]  (entity 1, query)
        v2 = [0, 1, 0, 0]  (entity 2, cos=0.0 → filtered)
        v3 ≈ [0.707, 0.707, 0, 0]  (entity 3, cos≈0.707)
        v4 = [0.5, 0.5, 0.5, 0.5]  (entity 4, cos=0.5  → at threshold)
        v5 = [0, 0, 1, 0]  (entity 5, cos=0.0 → filtered)
        """
        v1 = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
        v2 = np.array([0.0, 1.0, 0.0, 0.0], dtype="float32")
        v3 = np.array(
            [0.70710678, 0.70710678, 0.0, 0.0],
            dtype="float32",
        )
        v4 = np.array([0.5, 0.5, 0.5, 0.5], dtype="float32")
        v5 = np.array([0.0, 0.0, 1.0, 0.0], dtype="float32")

        # All are unit vectors by construction
        for eid, v in [(1, v1), (2, v2), (3, v3), (4, v4), (5, v5)]:
            _insert_node(self.con, eid, "code")
            _put_embedding_simple(self.con, eid, "code", v)

    # ------------------------------------------------------------------
    # Core ranking
    # ------------------------------------------------------------------

    def test_known_vectors_returns_correct_neighbors(self):
        """Known cosine values produce correct ranking above threshold."""
        self._setup_vectors_5()
        with mock.patch(
            "semantic.neighbors.resolve_candidate_ids",
            return_value=({2, 3, 4, 5}, {2: "T", 3: "T", 4: "T", 5: "T"}),
        ):
            result = find_neighbors(1, "code", self.con, k=5)

        # v3 (cos=0.707) and v4 (cos=0.5) are above threshold;
        # v2 and v5 (cos=0.0) are filtered out.
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], 3)
        self.assertAlmostEqual(result[0][1], 0.70710678, places=5)
        self.assertEqual(result[1][0], 4)
        self.assertAlmostEqual(result[1][1], 0.5, places=5)

    def test_self_excluded(self):
        """Query entity never appears in results."""
        self._setup_vectors_5()
        with mock.patch(
            "semantic.neighbors.resolve_candidate_ids",
            return_value=({1, 2, 3, 4, 5}, {1: "T", 2: "T", 3: "T", 4: "T", 5: "T"}),
        ):
            result = find_neighbors(1, "code", self.con, k=5)

        ids = {eid for eid, _ in result}
        self.assertNotIn(1, ids)

    def test_threshold_filter_excludes_low_similarity(self):
        """All candidates below 0.5 returns empty list."""
        v1 = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
        v2 = np.array([0.0, 1.0, 0.0, 0.0], dtype="float32")
        _insert_node(self.con, 1, "code")
        _put_embedding_simple(self.con, 1, "code", v1)
        _insert_node(self.con, 2, "code")
        _put_embedding_simple(self.con, 2, "code", v2)

        with mock.patch(
            "semantic.neighbors.resolve_candidate_ids",
            return_value=({2}, {2: "T"}),
        ):
            result = find_neighbors(1, "code", self.con, k=5)

        self.assertEqual(result, [])

    def test_descending_order(self):
        """Results sorted by score desc, ties by entity_id asc."""
        nodes: list[tuple[int, np.ndarray]] = [
            (9, np.array([0.5, 0.5, 0.5, 0.5], dtype="float32")),
            (7, np.array([0.7, 0.3, 0.0, 0.0], dtype="float32")),
            (8, np.array([0.7, 0.3, 0.0, 0.0], dtype="float32")),
        ]
        v_query = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")

        # Cosines: 9≈0.5, 7≈0.7, 8≈0.7  → order: 7, 8, 9
        _insert_node(self.con, 1, "code")
        _put_embedding_simple(self.con, 1, "code", v_query)
        all_ids = set()
        for eid, v in nodes:
            # Use a tag that normalises to unit
            nv = v / np.linalg.norm(v)
            _insert_node(self.con, eid, "code")
            _put_embedding_simple(self.con, eid, "code", nv)
            all_ids.add(eid)

        with mock.patch(
            "semantic.neighbors.resolve_candidate_ids",
            return_value=(all_ids, {eid: "T" for eid in all_ids}),
        ):
            result = find_neighbors(1, "code", self.con, k=5)

        self.assertEqual([eid for eid, _ in result], [7, 8, 9])

    # ------------------------------------------------------------------
    # k behavior
    # ------------------------------------------------------------------

    def test_k_default(self):
        """Default k=5 returns up to 5 neighbors."""
        v1 = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype="float32")
        _insert_node(self.con, 1, "code")
        _put_embedding_simple(self.con, 1, "code", v1)

        candidates = set()
        tag_map = {}
        for i in range(2, 12):
            v = np.zeros(6, dtype="float32")
            v[0] = 0.8
            v[i % 5 + 1] = np.sqrt(1.0 - 0.64)  # ensure unit norm
            _insert_node(self.con, i, "code")
            _put_embedding_simple(self.con, i, "code", v)
            candidates.add(i)
            tag_map[i] = "T"

        with mock.patch(
            "semantic.neighbors.resolve_candidate_ids",
            return_value=(candidates, tag_map),
        ):
            result = find_neighbors(1, "code", self.con)

        self.assertEqual(len(result), 5)

    def test_k_configurable(self):
        """k=3 returns exactly 3 results when enough above threshold."""
        v1 = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
        _insert_node(self.con, 1, "code")
        _put_embedding_simple(self.con, 1, "code", v1)

        candidates = set()
        tag_map = {}
        for i in range(2, 8):
            v = np.array([0.8, 0.6, 0.0, 0.0], dtype="float32")
            _insert_node(self.con, i, "code")
            _put_embedding_simple(self.con, i, "code", v)
            candidates.add(i)
            tag_map[i] = "T"

        with mock.patch(
            "semantic.neighbors.resolve_candidate_ids",
            return_value=(candidates, tag_map),
        ):
            result = find_neighbors(1, "code", self.con, k=3)

        self.assertEqual(len(result), 3)

    def test_k_clamped_to_max(self):
        """k above 20 is clamped to 20."""
        _insert_node(self.con, 1, "code")
        v1 = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
        _put_embedding_simple(self.con, 1, "code", v1)

        candidates = set()
        tag_map = {}
        for i in range(2, 42):
            v = np.array([0.8, 0.6, 0.0, 0.0], dtype="float32")
            _insert_node(self.con, i, "code")
            _put_embedding_simple(self.con, i, "code", v)
            candidates.add(i)
            tag_map[i] = "T"

        with mock.patch(
            "semantic.neighbors.resolve_candidate_ids",
            return_value=(candidates, tag_map),
        ):
            result = find_neighbors(1, "code", self.con, k=25)

        self.assertLessEqual(len(result), 20)

    def test_k_min_one(self):
        """k=0 is clamped to 1."""
        v1 = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
        v2 = np.array([0.8, 0.6, 0.0, 0.0], dtype="float32")
        _insert_node(self.con, 1, "code")
        _put_embedding_simple(self.con, 1, "code", v1)
        _insert_node(self.con, 2, "code")
        _put_embedding_simple(self.con, 2, "code", v2)

        with mock.patch(
            "semantic.neighbors.resolve_candidate_ids",
            return_value=({2}, {2: "T"}),
        ):
            result = find_neighbors(1, "code", self.con, k=0)

        self.assertEqual(len(result), 1)

    def test_fewer_than_k_above_threshold(self):
        """Only 2 candidates above 0.5 — returns 2, not padded."""
        v1 = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
        v2 = np.array([0.8, 0.6, 0.0, 0.0], dtype="float32")  # cos=0.8
        v3 = np.array([0.6, 0.8, 0.0, 0.0], dtype="float32")  # cos=0.6
        v4 = np.array([0.0, 1.0, 0.0, 0.0], dtype="float32")  # cos=0.0
        _insert_node(self.con, 1, "code")
        _put_embedding_simple(self.con, 1, "code", v1)
        for eid, v in [(2, v2), (3, v3), (4, v4)]:
            _insert_node(self.con, eid, "code")
            _put_embedding_simple(self.con, eid, "code", v)

        with mock.patch(
            "semantic.neighbors.resolve_candidate_ids",
            return_value=({2, 3, 4}, {2: "T", 3: "T", 4: "T"}),
        ):
            result = find_neighbors(1, "code", self.con, k=10)

        self.assertEqual(len(result), 2)

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_empty_scope(self):
        """No candidates in scope returns empty list."""
        _insert_node(self.con, 1, "code")
        v1 = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
        _put_embedding_simple(self.con, 1, "code", v1)

        with mock.patch(
            "semantic.neighbors.resolve_candidate_ids",
            return_value=(set(), {}),
        ):
            result = find_neighbors(1, "code", self.con)

        self.assertEqual(result, [])

    def test_entity_not_found_raises_key_error(self):
        """Non-existent entity_id raises KeyError."""
        v = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
        _insert_node(self.con, 2, "code")
        _put_embedding_simple(self.con, 2, "code", v)

        with self.assertRaises(KeyError):
            find_neighbors(99, "code", self.con)

    def test_no_query_embedding_returns_empty(self):
        """Entity with no cached embedding returns empty list."""
        _insert_node(self.con, 1, "code")
        # No embedding for entity 1
        _insert_node(self.con, 2, "code")
        v2 = np.array([0.8, 0.6, 0.0, 0.0], dtype="float32")
        _put_embedding_simple(self.con, 2, "code", v2)

        with mock.patch(
            "semantic.neighbors.resolve_candidate_ids",
            return_value=({2}, {2: "T"}),
        ):
            result = find_neighbors(1, "code", self.con)

        self.assertEqual(result, [])

    def test_no_candidate_embeddings_returns_empty(self):
        """All candidate embeddings missing returns empty list."""
        v1 = np.array([1.0, 0.0, 0.0, 0.0], dtype="float32")
        _insert_node(self.con, 1, "code")
        _put_embedding_simple(self.con, 1, "code", v1)
        _insert_node(self.con, 2, "code")
        # No embedding for entity 2

        with mock.patch(
            "semantic.neighbors.resolve_candidate_ids",
            return_value=({2}, {2: "T"}),
        ):
            result = find_neighbors(1, "code", self.con)

        self.assertEqual(result, [])

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def test_cache_hit_avoids_recomputation(self):
        """Second call within TTL returns cached without recompute."""
        self._setup_vectors_5()

        with mock.patch(
            "semantic.neighbors.resolve_candidate_ids",
            return_value=({2, 3, 4, 5}, {2: "T", 3: "T", 4: "T", 5: "T"}),
        ):
            result1 = find_neighbors(1, "code", self.con, k=5)

        # Second call: mock raises if resolve_candidate_ids is touched
        with mock.patch(
            "semantic.neighbors.resolve_candidate_ids",
            side_effect=RuntimeError("should not be called"),
        ):
            result2 = find_neighbors(1, "code", self.con, k=5)

        self.assertEqual(result1, result2)

    def test_cache_miss_different_k(self):
        """Different k values produce different cache keys."""
        self._setup_vectors_5()

        with mock.patch(
            "semantic.neighbors.resolve_candidate_ids",
            return_value=({2, 3, 4, 5}, {2: "T", 3: "T", 4: "T", 5: "T"}),
        ):
            r1 = find_neighbors(1, "code", self.con, k=1)
            r2 = find_neighbors(1, "code", self.con, k=2)

        self.assertNotEqual(r1, r2)

    def test_cache_expiry(self):
        """After TTL elapses, cache entry is evicted and recomputed."""
        self._setup_vectors_5()
        orig_monotonic = time_module.monotonic

        with (
            mock.patch(
                "semantic.neighbors.time.monotonic",
            ) as mock_time,
            mock.patch(
                "semantic.neighbors.resolve_candidate_ids",
                return_value=({2, 3, 4, 5}, {2: "T", 3: "T", 4: "T", 5: "T"}),
            ) as mock_resolve,
        ):
            mock_time.return_value = 1000.0
            _ = find_neighbors(1, "code", self.con, k=5)
            mock_resolve.assert_called_once()
            mock_resolve.reset_mock()

            # Advance just within TTL
            mock_time.return_value = 1000.0 + _CACHE_TTL - 1
            _ = find_neighbors(1, "code", self.con, k=5)
            mock_resolve.assert_not_called()
            mock_resolve.reset_mock()

            # Advance beyond TTL
            mock_time.return_value = 1000.0 + _CACHE_TTL + 1
            _ = find_neighbors(1, "code", self.con, k=5)
            mock_resolve.assert_called_once()

    def test_clear_cache(self):
        """clear_neighbor_cache empties the cache."""
        self._setup_vectors_5()

        with mock.patch(
            "semantic.neighbors.resolve_candidate_ids",
            return_value=({2, 3, 4, 5}, {2: "T", 3: "T", 4: "T", 5: "T"}),
        ):
            _ = find_neighbors(1, "code", self.con, k=5)

        self.assertIn((1, 5), _CACHE)
        clear_neighbor_cache()
        self.assertNotIn((1, 5), _CACHE)

    def test_cache_cleared_in_teardown(self):
        """Each test starts with a fresh cache (via tearDown)."""
        self.assertEqual(_CACHE, {})


if __name__ == "__main__":
    unittest.main()
