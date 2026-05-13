"""Comprehensive unit tests for embedding_cache CRUD operations.

Tests cover:
- Schema: table exists, columns, primary key, index on content_hash
- CRUD: put, get (including model_hash matching), upsert, invalidate_entity
- Bulk invalidation by content_hash
- Model hash computation reproducibility
- Serialization/deserialization of float32 NumPy arrays
"""

# flake8: noqa: E402
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

import hashlib
from typing import cast

import duckdb
import numpy as np
from persistence import (
    compute_model_hash,
    get_cache_stats,
    get_embedding,
    invalidate_by_content_hash,
    invalidate_entity,
    put_embedding,
)
from persistence.duckdb_init import initialize_database


class TestEmbeddingCacheSchema(unittest.TestCase):
    """Tests for embedding_cache table schema and constraints."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_embedding_cache.duckdb"

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_table_exists(self) -> None:
        """embedding_cache table is created by initialize_database."""
        initialize_database(db_path=self.db_path)
        con = duckdb.connect(str(self.db_path))
        try:
            tables = con.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'main' AND table_type='BASE TABLE';
                """
            ).fetchall()
            table_names = {row[0] for row in tables}
            self.assertIn("embedding_cache", table_names)
        finally:
            con.close()

    def test_table_schema_columns(self) -> None:
        """embedding_cache has the required columns with correct types."""
        initialize_database(db_path=self.db_path)
        con = duckdb.connect(str(self.db_path))
        try:
            cols = con.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'embedding_cache'
                ORDER BY ordinal_position;
                """
            ).fetchall()
            col_dict = {row[0]: row for row in cols}

            # Required columns present
            expected_cols = {
                "entity_id",
                "entity_type",
                "embedding",
                "model_hash",
                "content_hash",
                "timestamp",
            }
            self.assertEqual(expected_cols, set(col_dict.keys()))

            # entity_id VARCHAR NOT NULL
            self.assertIn("VARCHAR", col_dict["entity_id"][1].upper())
            self.assertEqual("NO", col_dict["entity_id"][2])

            # entity_type VARCHAR NOT NULL
            self.assertIn("VARCHAR", col_dict["entity_type"][1].upper())
            self.assertEqual("NO", col_dict["entity_type"][2])

            # embedding BLOB NOT NULL
            self.assertIn("BLOB", col_dict["embedding"][1].upper())
            self.assertEqual("NO", col_dict["embedding"][2])

            # model_hash VARCHAR NOT NULL
            self.assertIn("VARCHAR", col_dict["model_hash"][1].upper())
            self.assertEqual("NO", col_dict["model_hash"][2])

            # content_hash VARCHAR NOT NULL
            self.assertIn("VARCHAR", col_dict["content_hash"][1].upper())
            self.assertEqual("NO", col_dict["content_hash"][2])

            # timestamp TIMESTAMP with DEFAULT CURRENT_TIMESTAMP
            self.assertIn("TIMESTAMP", col_dict["timestamp"][1].upper())
        finally:
            con.close()

    def test_primary_key_constraint(self) -> None:
        """Primary key (entity_id, entity_type) is enforced."""
        initialize_database(db_path=self.db_path)
        con = duckdb.connect(str(self.db_path))
        try:
            # Insert first row should succeed
            con.execute(
                "INSERT INTO embedding_cache VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                ["e1", "exemplar", b"abc", "mh1", "ch1"],
            )
            # Second insert with same PK should fail (ON CONFLICT not used here
            # in this test; we want to verify PK exists)
            with self.assertRaises(duckdb.Error):
                con.execute(
                    "INSERT INTO embedding_cache VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                    ["e1", "exemplar", b"def", "mh2", "ch2"],
                )
        finally:
            con.close()

    def test_content_hash_index_exists(self) -> None:
        """Non-unique index idx_embedding_cache_content_hash exists on content_hash."""
        initialize_database(db_path=self.db_path)
        con = duckdb.connect(str(self.db_path))
        try:
            indexes = con.execute("SELECT index_name FROM duckdb_indexes();").fetchall()
            index_names = {row[0] for row in indexes}
            self.assertIn("idx_embedding_cache_content_hash", index_names)
        finally:
            con.close()


class TestEmbeddingCacheOperations(unittest.TestCase):
    """Tests for CRUD operations: put, get, invalidate."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_ops.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))

    def tearDown(self) -> None:
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_put_and_get_roundtrip(self) -> None:
        """put_embedding stores an array; get_embedding retrieves identical array."""
        entity_id = "exemplar_001"
        entity_type = "exemplar"
        model = "all-MiniLM-L6-v2"
        content = "test content hash for exemplar"
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        model_hash = compute_model_hash(model)

        # Generate random embedding
        original = np.random.rand(384).astype("float32")

        put_embedding(
            self.con, entity_id, entity_type, original, model_hash, content_hash
        )

        retrieved = get_embedding(self.con, entity_id, entity_type)
        self.assertIsNotNone(retrieved)
        retrieved = cast(np.ndarray, retrieved)
        self.assertTrue(np.array_equal(original, retrieved))
        self.assertEqual(retrieved.dtype, np.float32)

    def test_get_missing_returns_none(self) -> None:
        """get_embedding returns None if entity is not in cache."""
        result = get_embedding(self.con, "nonexistent", "exemplar")
        self.assertIsNone(result)

    def test_get_model_hash_mismatch_returns_none(self) -> None:
        """Cache miss when stored model_hash differs from requested model_hash."""
        entity_id = "code_001"
        entity_type = "code"
        content = "definition text"
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        model_v1 = "model_v1"
        model_v2 = "model_v2"
        mh1 = compute_model_hash(model_v1)
        mh2 = compute_model_hash(model_v2)
        emb = np.random.rand(384).astype("float32")

        put_embedding(self.con, entity_id, entity_type, emb, mh1, content_hash)

        # Request with different model_hash should return None
        retrieved = get_embedding(self.con, entity_id, entity_type, model_hash=mh2)
        self.assertIsNone(retrieved)

        # Request with matching model_hash returns the embedding
        retrieved = get_embedding(self.con, entity_id, entity_type, model_hash=mh1)
        self.assertIsNotNone(retrieved)
        self.assertTrue(np.array_equal(emb, retrieved))

    def test_upsert_updates_existing_entry(self) -> None:
        """Putting the same (entity_id, entity_type) twice updates the row."""
        entity_id = "theme_001"
        entity_type = "theme"
        content = "theme definition"
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        mh = compute_model_hash("model")
        emb1 = np.random.rand(384).astype("float32")
        emb2 = np.random.rand(384).astype("float32")

        put_embedding(self.con, entity_id, entity_type, emb1, mh, content_hash)
        put_embedding(self.con, entity_id, entity_type, emb2, mh, content_hash)

        # Should retrieve the second embedding
        retrieved = get_embedding(self.con, entity_id, entity_type, model_hash=mh)
        self.assertIsNotNone(retrieved)
        self.assertTrue(np.array_equal(emb2, retrieved))

        # Count should be 1 (no duplicate rows)
        count = self.con.execute(
            "SELECT COUNT(*) FROM embedding_cache WHERE entity_id = ? AND entity_type = ?",
            [entity_id, entity_type],
        ).fetchone()[0]
        self.assertEqual(1, count)

    def test_invalidate_entity_removes_row(self) -> None:
        """invalidate_entity deletes the cache entry for an entity."""
        entity_id = "interpretation_001"
        entity_type = "interpretation"
        content = "some long interpretation text"
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        mh = compute_model_hash("model")
        emb = np.random.rand(384).astype("float32")

        put_embedding(self.con, entity_id, entity_type, emb, mh, content_hash)
        self.assertIsNotNone(get_embedding(self.con, entity_id, entity_type))

        deleted = invalidate_entity(self.con, entity_id, entity_type)
        self.assertEqual(1, deleted)
        self.assertIsNone(get_embedding(self.con, entity_id, entity_type))

    def test_invalidate_nonexistent_returns_zero(self) -> None:
        """Invalidating a non-existent entity returns 0 and does not raise."""
        deleted = invalidate_entity(self.con, "does_not_exist", "code")
        self.assertEqual(0, deleted)

    def test_invalidate_by_content_hash_removes_matching(self) -> None:
        """Bulk invalidation removes all entries with the given content_hash."""
        ch_common = "commonhash123"
        mh = compute_model_hash("model")

        # Insert several rows; two share content_hash, one different
        for i in range(3):
            put_embedding(
                self.con,
                f"e{i}",
                "exemplar",
                np.random.rand(384).astype("float32"),
                mh,
                ch_common,
            )
        put_embedding(
            self.con,
            "other",
            "exemplar",
            np.random.rand(384).astype("float32"),
            mh,
            "differenthash",
        )

        deleted = invalidate_by_content_hash(self.con, ch_common)
        self.assertEqual(3, deleted)

        # Verify survivors
        remaining = self.con.execute(
            "SELECT COUNT(*) FROM embedding_cache WHERE content_hash = ?",
            [ch_common],
        ).fetchone()[0]
        self.assertEqual(0, remaining)

        other_count = self.con.execute(
            "SELECT COUNT(*) FROM embedding_cache WHERE content_hash = ?",
            ["differenthash"],
        ).fetchone()[0]
        self.assertEqual(1, other_count)

    def test_compute_model_hash_deterministic(self) -> None:
        """compute_model_hash returns consistent 16-char hex strings."""
        model_name = "all-MiniLM-L6-v2"
        h1 = compute_model_hash(model_name)
        h2 = compute_model_hash(model_name)
        self.assertEqual(h1, h2)
        self.assertEqual(16, len(h1))
        # Verify hex characters
        self.assertRegex(h1, r"^[0-9a-f]+$")

    def test_get_cache_stats(self) -> None:
        """get_cache_stats returns correct aggregate counts."""
        mh = compute_model_hash("model")
        # Insert variety
        for et in ["exemplar", "code", "theme"]:
            for i in range(2):
                put_embedding(
                    self.con,
                    f"{et}_{i}",
                    et,
                    np.random.rand(384).astype("float32"),
                    mh,
                    f"hash_{et}_{i}",
                )

        stats = get_cache_stats(self.con)
        self.assertEqual(6, stats["total"])
        self.assertEqual(
            {"exemplar": 2, "code": 2, "theme": 2}, stats["by_entity_type"]
        )
        self.assertIsNotNone(stats["oldest"])
        self.assertIsNotNone(stats["newest"])

    def test_serialization_float32_preserved(self) -> None:
        """Embedding dtype is always stored and retrieved as float32."""
        # Test various input dtypes
        test_arrays = [
            np.array([1.0, 2.0, 3.0], dtype=np.float64),
            np.array([1, 2, 3], dtype=np.int32),
            np.array([1.5, 2.5, 3.5], dtype=np.float16),
        ]
        entity_id = "dtype_test"
        content_hash = "test"
        mh = "mh"

        for idx, arr_input in enumerate(test_arrays):
            put_embedding(
                self.con,
                f"{entity_id}_{idx}",
                "exemplar",
                arr_input,
                mh,
                content_hash,
            )
            retrieved = get_embedding(self.con, f"{entity_id}_{idx}", "exemplar")
            self.assertIsNotNone(retrieved)
            retrieved = cast(np.ndarray, retrieved)
            self.assertEqual(np.float32, retrieved.dtype)
            # Values should match after float32 conversion
            np.testing.assert_allclose(
                arr_input.astype("float32"), retrieved, rtol=1e-6
            )

    def test_empty_embedding_array(self) -> None:
        """Zero-length embedding arrays are stored and retrieved."""
        entity_id = "empty_emb"
        content_hash = "empty"
        mh = compute_model_hash("model")
        empty = np.array([], dtype="float32")

        put_embedding(self.con, entity_id, "exemplar", empty, mh, content_hash)
        retrieved = get_embedding(self.con, entity_id, "exemplar")
        self.assertIsNotNone(retrieved)
        retrieved = cast(np.ndarray, retrieved)
        self.assertEqual(0, retrieved.shape[0])
        self.assertTrue(np.array_equal(empty, retrieved))


if __name__ == "__main__":
    unittest.main()
