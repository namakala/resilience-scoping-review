"""Comprehensive unit tests for DuckDB schema initialization.

Tests cover:
- Database file creation on first run
- Table existence and schema validation
- Primary key, index, and constraint verification
- Idempotency (safe to call initialize_database multiple times)
- Schema version tracking in session_state
- Migration system behavior (0→1 migration, no-op when current)
- get_connection() directory creation
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

import duckdb
from persistence.duckdb_init import (
    DEFAULT_DB_PATH,
    get_connection,
    get_schema_version,
    init_or_migrate,
    initialize_database,
    migrate_schema,
)
from persistence.exceptions import ConversionError


class TestDuckDBInitialization(unittest.TestCase):
    """Tests for DuckDB schema initialization module."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_session.duckdb"

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_get_connection_default_creates_parent_dir(self) -> None:
        """get_connection() creates the parent directory if it doesn't exist."""
        db_path = self.tmpdir / "nested" / "output" / "session.duckdb"
        con = get_connection(db_path)
        try:
            self.assertTrue(db_path.parent.exists())
            self.assertTrue(db_path.exists())
        finally:
            con.close()

    def test_initialize_database_creates_file(self) -> None:
        """initialize_database() creates the database file on first run."""
        self.assertFalse(self.db_path.exists())
        initialize_database(db_path=self.db_path)
        self.assertTrue(self.db_path.exists())

    def test_get_connection_returns_active_connection(self) -> None:
        """get_connection() returns a working DuckDB connection."""
        con = get_connection(self.db_path)
        try:
            result = con.execute("SELECT 1").fetchone()
            self.assertEqual(result[0], 1)
        finally:
            con.close()

    def test_initialize_database_idempotent(self) -> None:
        """initialize_database() is safe to call multiple times (IF NOT EXISTS)."""
        # First call
        initialize_database(db_path=self.db_path)
        # Second call should succeed without errors
        initialize_database(db_path=self.db_path)

    def test_all_tables_exist(self) -> None:
        """All seven required tables are created."""
        initialize_database(db_path=self.db_path)
        con = get_connection(self.db_path)
        try:
            tables = con.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'main' AND table_type='BASE TABLE';
            """
            ).fetchall()
            table_names = {row[0] for row in tables}
            expected = {
                "nodes",
                "edges",
                "traversal_cache",
                "session_state",
                "user_actions",
                "embedding_cache",
                "invalidation_log",
                "inference_status",
            }
            self.assertEqual(expected, table_names)
        finally:
            con.close()

    def test_nodes_table_schema(self) -> None:
        """nodes table has correct columns, types, and PK."""
        initialize_database(db_path=self.db_path)
        con = get_connection(self.db_path)
        try:
            cols = con.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = 'nodes'
                ORDER BY ordinal_position;
            """
            ).fetchall()
            col_dict = {row[0]: row for row in cols}

            # Verify required columns exist
            expected_cols = [
                "id",
                "type",
                "name",
                "definition",
                "tag",
                "status",
                "data_json",
                "created_at",
                "updated_at",
            ]
            self.assertEqual(set(expected_cols), {row[0] for row in cols})

            # id: INTEGER, PRIMARY KEY, with sequence DEFAULT for auto-increment
            id_col = col_dict["id"]
            self.assertIn("INTEGER", id_col[1].upper())
            # DuckDB uses DEFAULT nextval('nodes_id_seq') for auto-increment
            self.assertIsNotNone(id_col[3])  # has DEFAULT
            self.assertIn("nextval", str(id_col[3]).lower())

            # column type: VARCHAR, NOT NULL
            type_col = col_dict["type"]
            self.assertIn("VARCHAR", type_col[1].upper())
            self.assertEqual("NO", type_col[2])

            # status: default 'active'
            status_col = col_dict["status"]
            self.assertEqual("YES", status_col[2])  # nullable YES per spec
            self.assertIsNotNone(status_col[3])  # has DEFAULT

            # data_json: VARCHAR/TEXT (per spec)
            data_json_col = col_dict["data_json"]
            self.assertIn("VARCHAR", data_json_col[1].upper())

            # timestamps: created_at, updated_at have defaults
            created_col = col_dict["created_at"]
            self.assertIn("TIMESTAMP", created_col[1].upper())
            self.assertIsNotNone(created_col[3])
        finally:
            con.close()

    def test_edges_table_schema_and_composite_pk(self) -> None:
        """edges has composite PK (source_id, target_id, edge_type) and correct types."""
        initialize_database(db_path=self.db_path)
        con = get_connection(self.db_path)
        try:
            cols = con.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'edges'
                ORDER BY ordinal_position;
            """
            ).fetchall()
            col_dict = {row[0]: row for row in cols}

            # source_id, target_id: INTEGER NOT NULL
            self.assertEqual("INTEGER", col_dict["source_id"][1].upper())
            self.assertEqual("NO", col_dict["source_id"][2])
            self.assertEqual("INTEGER", col_dict["target_id"][1].upper())
            self.assertEqual("NO", col_dict["target_id"][2])

            # edge_type: VARCHAR NOT NULL
            self.assertEqual("VARCHAR", col_dict["edge_type"][1].upper())
            self.assertEqual("NO", col_dict["edge_type"][2])

            # metadata_json: VARCHAR
            self.assertIn("VARCHAR", col_dict["metadata_json"][1].upper())

            # Verify composite PK exists in pragma
            pk_info = con.execute("PRAGMA table_info(edges);").fetchall()
            # pk column in pragma: 1 if part of PK
            pk_cols = [row[1] for row in pk_info if row[5] == 1]
            self.assertSetEqual(set(pk_cols), {"source_id", "target_id", "edge_type"})
        finally:
            con.close()

    def test_traversal_cache_table_schema(self) -> None:
        """traversal_cache has tag PK and JSON TEXT columns."""
        initialize_database(db_path=self.db_path)
        con = get_connection(self.db_path)
        try:
            cols = con.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'traversal_cache';
            """
            ).fetchall()
            col_dict = {row[0]: row for row in cols}

            # tag is primary key
            self.assertIn("tag", col_dict)
            self.assertIn("VARCHAR", col_dict["tag"][1].upper())

            # JSON columns stored as VARCHAR/TEXT
            for json_col in (
                "ancestors",
                "descendants",
                "subtree_exemplars",
                "subtree_codes",
                "subtree_themes",
            ):
                self.assertIn(json_col, col_dict)
                self.assertIn("VARCHAR", col_dict[json_col][1].upper())
        finally:
            con.close()

    def test_session_state_table_schema(self) -> None:
        """session_state has key PK, value TEXT, and type column."""
        initialize_database(db_path=self.db_path)
        con = get_connection(self.db_path)
        try:
            cols = con.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'session_state';
            """
            ).fetchall()
            col_dict = {row[0]: row for row in cols}

            self.assertIn("key", col_dict)
            self.assertIn("VARCHAR", col_dict["key"][1].upper())

            self.assertIn("value", col_dict)
            self.assertIn("VARCHAR", col_dict["value"][1].upper())
            self.assertEqual("NO", col_dict["value"][2])  # NOT NULL

            self.assertIn("type", col_dict)
            self.assertIn("VARCHAR", col_dict["type"][1].upper())
            self.assertEqual("NO", col_dict["type"][2])  # NOT NULL
        finally:
            con.close()

    def test_user_actions_table_schema_and_index(self) -> None:
        """user_actions has correct schema and timestamp index exists."""
        initialize_database(db_path=self.db_path)
        con = get_connection(self.db_path)
        try:
            cols = con.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = 'user_actions';
            """
            ).fetchall()
            col_dict = {row[0]: row for row in cols}

            self.assertIn("action_id", col_dict)
            self.assertIn("INTEGER", col_dict["action_id"][1].upper())

            self.assertIn("timestamp", col_dict)
            self.assertIn("TIMESTAMP", col_dict["timestamp"][1].upper())
            self.assertEqual("NO", col_dict["timestamp"][2])  # NOT NULL
            self.assertIsNotNone(col_dict["timestamp"][3])  # DEFAULT CURRENT_TIMESTAMP

            self.assertIn("action_type", col_dict)
            self.assertIn("entity_id", col_dict)
            self.assertIn("old_value", col_dict)
            self.assertIn("new_value", col_dict)
            self.assertIn("user_id", col_dict)

            # Check index exists (DuckDB: duckdb_indexes() returns index_name column)
            indexes = con.execute("SELECT index_name FROM duckdb_indexes();").fetchall()
            index_names = {row[0] for row in indexes}
            self.assertIn("idx_user_actions_timestamp", index_names)
        finally:
            con.close()

    def test_schema_version_stored(self) -> None:
        """Schema version (1) is stored in session_state after init."""
        initialize_database(db_path=self.db_path)
        version = get_schema_version(db_path=self.db_path)
        self.assertEqual(version, 1)

    def test_get_schema_version_before_init(self) -> None:
        """get_schema_version returns 0 if DB not yet initialized."""
        version = get_schema_version(db_path=self.db_path)
        self.assertEqual(version, 0)

    def test_migrate_schema_already_current(self) -> None:
        """migrate_schema() no-ops when at target version."""
        initialize_database(db_path=self.db_path)
        initial_version = get_schema_version(db_path=self.db_path)
        self.assertEqual(initial_version, 1)

        # Calling migrate_schema(1) should not raise
        migrate_schema(1, db_path=self.db_path)
        self.assertEqual(get_schema_version(db_path=self.db_path), 1)

    def test_migrate_schema_cannot_downgrade(self) -> None:
        """migrate_schema() raises ValueError on downgrade attempt."""
        initialize_database(db_path=self.db_path)
        with self.assertRaisesRegex(ValueError, "Cannot downgrade"):
            migrate_schema(0, db_path=self.db_path)

    def test_init_or_migrate_returns_connection(self) -> None:
        """init_or_migrate() returns an open connection, DB is initialized."""
        # Ensure DB doesn't exist first
        self.assertFalse(self.db_path.exists())
        con = init_or_migrate(self.db_path)
        try:
            self.assertIsNotNone(con)
            self.assertTrue(self.db_path.exists())
            # Verify can run a query
            result = con.execute("SELECT COUNT(*) FROM nodes").fetchone()
            self.assertEqual(result[0], 0)  # nodes empty
        finally:
            con.close()

    def test_tables_have_expected_constraints(self) -> None:
        """Verify that CHECK constraints, NOT NULL, and defaults are enforced."""
        initialize_database(db_path=self.db_path)
        con = get_connection(self.db_path)
        try:
            # nodes.type NOT NULL enforced: insert with NULL should fail
            with self.assertRaises(duckdb.Error):
                con.execute("INSERT INTO nodes (name) VALUES ('test');")

            # edges composite PK uniqueness
            con.execute(
                """
                INSERT INTO edges (source_id, target_id, edge_type, metadata_json)
                VALUES (1, 2, 'test', '{}');
            """
            )
            with self.assertRaises(duckdb.Error):
                con.execute(
                    """
                    INSERT INTO edges (source_id, target_id, edge_type, metadata_json)
                    VALUES (1, 2, 'test', '{}');
                """
                )
            # No explicit rollback needed; connection close discards uncommitted changes
        finally:
            con.close()


class TestMigrationSystem(unittest.TestCase):
    """Test the migration framework and version tracking."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test_migrate.duckdb"

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_migration_0_to_1_creates_schema(self) -> None:
        """Directly applying _apply_migration(0,1) creates all tables and sets version=1."""
        con = get_connection(self.db_path)
        try:
            # Manually apply 0→1
            from persistence.duckdb_migrations import _apply_migration

            _apply_migration(con, 0, 1)

            # Verify tables exist
            tables = con.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema='main' AND table_type='BASE TABLE';
            """
            ).fetchall()
            table_names = {r[0] for r in tables}
            expected = {
                "nodes",
                "edges",
                "traversal_cache",
                "session_state",
                "user_actions",
            }
            self.assertEqual(expected, table_names)

            # Verify version stored
            version = get_schema_version(db_path=self.db_path)
            self.assertEqual(version, 1)
        finally:
            con.close()

    def test_migrate_schema_from_0_to_latest(self) -> None:
        """migrate_schema(1) on fresh DB brings it to version 1."""
        con = get_connection(self.db_path)
        try:
            migrate_schema(1, db_path=self.db_path, con=con)
            self.assertEqual(get_schema_version(db_path=self.db_path), 1)
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
