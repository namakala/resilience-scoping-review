"""Tests for inference/inference_status_types.py — constants and DDL."""

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
from inference.inference_status_types import INFERENCE_STATUS_DDL, _validate_params


class TestTableCreation(unittest.TestCase):
    """Table schema, defaults, idempotency, composite PK."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "test.duckdb"
        self.con = duckdb.connect(str(self.db_path))
        self.con.execute(INFERENCE_STATUS_DDL)

    def tearDown(self):
        self.con.close()
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_table_exists(self):
        tables = self.con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
        ).fetchall()
        names = {row[0] for row in tables}
        self.assertIn("inference_status", names)

    def test_columns_and_types(self):
        cols = self.con.execute(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_name = 'inference_status' "
            "ORDER BY ordinal_position"
        ).fetchall()
        col_dict = {row[0]: (row[1], row[2]) for row in cols}
        expected = {
            "entity_id": ("VARCHAR", "NO"),
            "entity_type": ("VARCHAR", "NO"),
            "stage": ("VARCHAR", "NO"),
            "status": ("VARCHAR", "NO"),
            "last_attempt_at": ("TIMESTAMP", "YES"),
            "attempts": ("INTEGER", "YES"),
        }
        for col_name, (dtype, nullable) in expected.items():
            self.assertIn(col_name, col_dict)
            self.assertIn(dtype.upper(), col_dict[col_name][0].upper(), col_name)
            self.assertEqual(nullable, col_dict[col_name][1], col_name)

    def test_composite_primary_key(self):
        pk_info = self.con.execute("PRAGMA table_info(inference_status)").fetchall()
        pk_cols = {row[1] for row in pk_info if row[5] == 1}
        self.assertSetEqual(pk_cols, {"entity_id", "entity_type", "stage"})

    def test_ddl_idempotent(self):
        self.con.execute(INFERENCE_STATUS_DDL)

    def test_default_status_is_pending(self):
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage) "
            "VALUES ('e1', 'exemplar', 'code')"
        )
        row = self.con.execute(
            "SELECT status FROM inference_status WHERE entity_id = 'e1'"
        ).fetchone()
        self.assertEqual(row[0], "pending")

    def test_default_attempts_is_zero(self):
        self.con.execute(
            "INSERT INTO inference_status (entity_id, entity_type, stage) "
            "VALUES ('e1', 'exemplar', 'code')"
        )
        row = self.con.execute(
            "SELECT attempts FROM inference_status WHERE entity_id = 'e1'"
        ).fetchone()
        self.assertEqual(row[0], 0)


if __name__ == "__main__":
    unittest.main()
