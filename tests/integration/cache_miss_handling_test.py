"""Integration tests for cache-miss-handling (Feature 57).

Tests the full path:
- Session A stores results in node_cache
- Session B (new process) loads cached results (cross-session reuse)
- Corrupted cache entries are auto-rebuilt
- Cache hit/miss counts are accurate
- Exclusive lock/unlock for node cache
"""

# flake8: noqa: E402
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent / "src" / "python"),
)

import duckdb
from persistence import load_cached, store_cached
from persistence.duckdb_init import initialize_database

# ── Mock Hamilton node (for real-object serialization tests) ─────────
SAMPLE_GRAPH_DATA = {
    "nodes": [
        {"name": "code_1", "definition": "First code", "tag": "Problem"},
        {"name": "code_2", "definition": "Second code", "tag": "Problem.Cause"},
    ],
    "count": 2,
}

SAMPLE_EMBEDDING_RESULT = {
    "entity_type": "exemplar",
    "count": 3,
    "entries": {
        "id": ["e1", "e2", "e3"],
        "embedding": [
            [0.1, 0.2, 0.3],
            [0.4, 0.5, 0.6],
            [0.7, 0.8, 0.9],
        ],
    },
}


class TestCacheMissHandlingIntegration(unittest.TestCase):
    """End-to-end cross-session cache behavior."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "session.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))

    def tearDown(self) -> None:
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)

    # ── Session A: store ─────────────────────────────────────────────

    def _session_a_store(self) -> dict[str, str]:
        """Simulate first pipeline run — store results."""
        hashes = {}
        for node_id, result, inputs in [
            (
                "retrieve_code_candidates",
                SAMPLE_GRAPH_DATA,
                {"query_tag": "Problem", "k": 50},
            ),
            (
                "cache_exemplar_embeddings",
                SAMPLE_EMBEDDING_RESULT,
                {"batch_size": 32, "model": "all-MiniLM-L6-v2"},
            ),
        ]:
            canonical = json.dumps(inputs, sort_keys=True)
            inputs_hash = hashlib.sha256(canonical.encode()).hexdigest()
            store_cached(self.con, node_id, inputs_hash, result)
            hashes[node_id] = inputs_hash
        return hashes

    # ── Session B: load ──────────────────────────────────────────────

    def _session_b_load(self, hashes: dict[str, str]) -> dict[str, object | None]:
        """Simulate second pipeline run — load cached results."""
        loaded = {}
        for node_id, inputs_hash in hashes.items():
            loaded[node_id] = load_cached(self.con, node_id, inputs_hash)
        return loaded

    # ── Tests ────────────────────────────────────────────────────────

    def test_cross_session_cache_hit(self) -> None:
        """Cache persists across sessions: store → close → reopen → hit."""
        hashes = self._session_a_store()
        self.con.close()

        # Re-open (simulate new process)
        con2 = duckdb.connect(str(self.db_path))
        try:
            loaded = {}
            for node_id, inputs_hash in hashes.items():
                loaded[node_id] = load_cached(con2, node_id, inputs_hash)
            self.assertIsNotNone(loaded["retrieve_code_candidates"])
            self.assertIsNotNone(loaded["cache_exemplar_embeddings"])
            self.assertEqual(SAMPLE_GRAPH_DATA, loaded["retrieve_code_candidates"])
        finally:
            con2.close()

    def test_cache_miss_on_hash_change(self) -> None:
        """Changing inputs_hash produces a cache miss."""
        self._session_a_store()

        changed_hash = hashlib.sha256(b"different_inputs").hexdigest()
        loaded = load_cached(self.con, "retrieve_code_candidates", changed_hash)
        self.assertIsNone(loaded)

    def test_cache_miss_on_missing_entry(self) -> None:
        """Loading a non-existent node_id returns None."""
        loaded = load_cached(self.con, "nonexistent_node", "some_hash")
        self.assertIsNone(loaded)

    def test_corrupted_entry_auto_rebuilds(self) -> None:
        """Corrupted blob → DELETE → subsequent load returns None."""
        # Insert corrupted blob directly
        self.con.execute(
            "INSERT INTO node_cache (node_id, inputs_hash, output_blob) "
            "VALUES (?, ?, ?)",
            ["infer_codes", "corrupted_hash", b"garbage data"],
        )
        loaded = load_cached(self.con, "infer_codes", "corrupted_hash")
        self.assertIsNone(loaded)

        # Verify row was deleted
        remaining = self.con.execute(
            "SELECT COUNT(*) FROM node_cache WHERE node_id = ? AND inputs_hash = ?",
            ["infer_codes", "corrupted_hash"],
        ).fetchone()[0]
        self.assertEqual(0, remaining)

    def test_idempotent_store_reload(self) -> None:
        """Running the same store twice yields identical cached values."""
        first_hash = self._session_a_store()
        # Store again with same inputs
        second_hash = self._session_a_store()
        self.assertEqual(first_hash, second_hash)

        # Load from first store
        loaded_first = {}
        for node_id, inputs_hash in first_hash.items():
            loaded_first[node_id] = load_cached(self.con, node_id, inputs_hash)

        # Load from second store (same hashes, should be same data)
        loaded_second = {}
        for node_id, inputs_hash in second_hash.items():
            loaded_second[node_id] = load_cached(self.con, node_id, inputs_hash)

        self.assertEqual(loaded_first, loaded_second)

    def test_node_cache_table_exists(self) -> None:
        """node_cache table is created by initialize_database."""
        tables = self.con.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'main' AND table_type='BASE TABLE';
            """
        ).fetchall()
        table_names = {row[0] for row in tables}
        self.assertIn("node_cache", table_names)

    def test_cache_hit_rate_metric(self) -> None:
        """After full run, all stored entries produce cache hits."""
        hashes = self._session_a_store()
        total = len(hashes)

        hits = 0
        for node_id, inputs_hash in hashes.items():
            loaded = load_cached(self.con, node_id, inputs_hash)
            if loaded is not None:
                hits += 1

        self.assertEqual(total, hits)
        self.assertGreater(hits, 0)

    def test_partial_cache_result_isolation(self) -> None:
        """Different node IDs with same inputs_hash don't interfere."""
        common_hash = hashlib.sha256(b"same_input").hexdigest()
        result_a = {"node": "A", "data": [1, 2, 3]}
        result_b = {"node": "B", "data": [4, 5, 6]}

        store_cached(self.con, "node_A", common_hash, result_a)
        store_cached(self.con, "node_B", common_hash, result_b)

        loaded_a = load_cached(self.con, "node_A", common_hash)
        loaded_b = load_cached(self.con, "node_B", common_hash)

        self.assertEqual(result_a, loaded_a)
        self.assertEqual(result_b, loaded_b)
        self.assertNotEqual(loaded_a, loaded_b)


if __name__ == "__main__":
    unittest.main()
