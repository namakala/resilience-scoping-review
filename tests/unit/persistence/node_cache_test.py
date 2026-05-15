"""Unit tests for node_cache CRUD operations.

Covers:
- Schema: table exists, columns, primary key, index on inputs_hash
- CRUD: store, load (hit & miss), upsert, invalidation
- Corruption auto-rebuild: corrupted pickle blob -> DELETE -> returns None
"""

# flake8: noqa: E402
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

import duckdb
from persistence import clear_all_node_cache, invalidate_node, load_cached, store_cached
from persistence.duckdb_init import initialize_database


class TestNodeCacheSchema(unittest.TestCase):
    """Schema tests for the node_cache table."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_node_cache.duckdb"

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_table_exists(self) -> None:
        """node_cache table is created by initialize_database."""
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
            self.assertIn("node_cache", table_names)
        finally:
            con.close()

    def test_table_schema_columns(self) -> None:
        """node_cache has required columns with correct types."""
        initialize_database(db_path=self.db_path)
        con = duckdb.connect(str(self.db_path))
        try:
            cols = con.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'node_cache'
                ORDER BY ordinal_position;
                """
            ).fetchall()
            col_dict = {row[0]: row for row in cols}

            expected = {"node_id", "inputs_hash", "output_blob", "timestamp"}
            self.assertEqual(expected, set(col_dict.keys()))

            # node_id VARCHAR NOT NULL
            self.assertIn("VARCHAR", col_dict["node_id"][1].upper())
            self.assertEqual("NO", col_dict["node_id"][2])

            # inputs_hash VARCHAR NOT NULL
            self.assertIn("VARCHAR", col_dict["inputs_hash"][1].upper())
            self.assertEqual("NO", col_dict["inputs_hash"][2])

            # output_blob BLOB NOT NULL
            self.assertIn("BLOB", col_dict["output_blob"][1].upper())
            self.assertEqual("NO", col_dict["output_blob"][2])

            # timestamp TIMESTAMP
            self.assertIn("TIMESTAMP", col_dict["timestamp"][1].upper())
        finally:
            con.close()

    def test_primary_key_constraint(self) -> None:
        """Primary key (node_id, inputs_hash) prevents duplicates."""
        initialize_database(db_path=self.db_path)
        con = duckdb.connect(str(self.db_path))
        try:
            con.execute(
                "INSERT INTO node_cache VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                ["my_node", "hash1", b"first"],
            )
            with self.assertRaises(duckdb.Error):
                con.execute(
                    "INSERT INTO node_cache VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    ["my_node", "hash1", b"second"],
                )
        finally:
            con.close()

    def test_inputs_hash_index_exists(self) -> None:
        """Index idx_node_cache_inputs_hash exists."""
        initialize_database(db_path=self.db_path)
        con = duckdb.connect(str(self.db_path))
        try:
            indexes = con.execute("SELECT index_name FROM duckdb_indexes();").fetchall()
            index_names = {row[0] for row in indexes}
            self.assertIn("idx_node_cache_inputs_hash", index_names)
        finally:
            con.close()


class TestNodeCacheOperations(unittest.TestCase):
    """CRUD tests for store, load, invalidation."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_ops.duckdb"
        initialize_database(db_path=self.db_path)
        self.con = duckdb.connect(str(self.db_path))

    def tearDown(self) -> None:
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_store_and_load_roundtrip(self) -> None:
        """store_cached stores a result; load_cached retrieves it identically."""
        result = {"codes": ["code_a", "code_b"], "count": 2}
        store_cached(self.con, "infer_codes", "abc123", result)
        loaded = load_cached(self.con, "infer_codes", "abc123")
        self.assertEqual(result, loaded)

    def test_load_missing_returns_none(self) -> None:
        """load_cached returns None when no matching row exists."""
        loaded = load_cached(self.con, "nonexistent", "hash")
        self.assertIsNone(loaded)

    def test_different_hashes_do_not_collide(self) -> None:
        """Different inputs_hash values for the same node ID are separate entries."""
        store_cached(self.con, "my_node", "hash_a", "value_a")
        store_cached(self.con, "my_node", "hash_b", "value_b")

        loaded_a = load_cached(self.con, "my_node", "hash_a")
        loaded_b = load_cached(self.con, "my_node", "hash_b")
        self.assertEqual("value_a", loaded_a)
        self.assertEqual("value_b", loaded_b)

    def test_upsert_overwrites_existing(self) -> None:
        """Storing same (node_id, inputs_hash) twice overwrites (last-write-wins)."""
        store_cached(self.con, "node", "same_hash", "original")
        store_cached(self.con, "node", "same_hash", "updated")

        loaded = load_cached(self.con, "node", "same_hash")
        self.assertEqual("updated", loaded)

        count = self.con.execute(
            "SELECT COUNT(*) FROM node_cache WHERE node_id = ? AND inputs_hash = ?",
            ["node", "same_hash"],
        ).fetchone()[0]
        self.assertEqual(1, count)

    def test_complex_python_objects(self) -> None:
        """Nested dicts, lists, and primitives survive round-trip."""
        original = {
            "strings": ["a", "b"],
            "numbers": [1, 2.5],
            "nested": {"key": [True, None]},
            "mixed": [(1, 2)],
        }
        store_cached(self.con, "complex_node", "hash_c", original)
        loaded = load_cached(self.con, "complex_node", "hash_c")
        self.assertEqual(original, loaded)

    def test_corrupted_blob_auto_rebuilds(self) -> None:
        """load_cached deletes corrupted entries and returns None."""
        con = self.con
        # Insert deliberately corrupt blob
        con.execute(
            "INSERT INTO node_cache (node_id, inputs_hash, output_blob) "
            "VALUES (?, ?, ?)",
            ["corrupted_node", "some_hash", b"NOT VALID PICKLE DATA"],
        )

        loaded = load_cached(con, "corrupted_node", "some_hash")
        self.assertIsNone(loaded)

        # Verify row was deleted
        remaining = con.execute(
            "SELECT COUNT(*) FROM node_cache WHERE node_id = ? AND inputs_hash = ?",
            ["corrupted_node", "some_hash"],
        ).fetchone()[0]
        self.assertEqual(0, remaining)

    def test_invalidate_node(self) -> None:
        """invalidate_node removes all cache entries for a node."""
        for h in ["h1", "h2", "h3"]:
            store_cached(self.con, "target_node", h, f"val_{h}")
        store_cached(self.con, "other_node", "hx", "other")

        deleted = invalidate_node(self.con, "target_node")
        self.assertEqual(3, deleted)

        for h in ["h1", "h2", "h3"]:
            self.assertIsNone(load_cached(self.con, "target_node", h))
        # Other node is unaffected
        self.assertIsNotNone(load_cached(self.con, "other_node", "hx"))

    def test_invalidate_nonexistent_node_returns_zero(self) -> None:
        """invalidate_node on a node with no entries returns 0."""
        deleted = invalidate_node(self.con, "does_not_exist")
        self.assertEqual(0, deleted)

    def test_clear_all_node_cache(self) -> None:
        """clear_all_node_cache removes every row."""
        for i in range(5):
            store_cached(self.con, f"node_{i}", "hash", i)

        total = self.con.execute("SELECT COUNT(*) FROM node_cache").fetchone()[0]
        self.assertEqual(5, total)

        cleared = clear_all_node_cache(self.con)
        self.assertEqual(5, cleared)

        remaining = self.con.execute("SELECT COUNT(*) FROM node_cache").fetchone()[0]
        self.assertEqual(0, remaining)

    def test_empty_cache_clear_returns_zero(self) -> None:
        """Clearing an empty cache returns 0."""
        cleared = clear_all_node_cache(self.con)
        self.assertEqual(0, cleared)


if __name__ == "__main__":
    unittest.main()
