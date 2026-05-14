"""Integration tests: inference_status table created by duckdb_init."""

# flake8: noqa: E402
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

from inference.inference_status_crud import set_status
from inference.inference_status_queries import get_pending_items
from inference.inference_status_types import GENERATED, PENDING, STAGE_CODE


class TestDuckDBInitIntegration(unittest.TestCase):
    """The inference_status table is created by initialize_database()."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "session.duckdb"

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir)

    def test_initialize_database_creates_inference_status(self):
        from persistence.duckdb_connection import get_connection
        from persistence.duckdb_init import initialize_database

        initialize_database(db_path=self.db_path)
        con = get_connection(self.db_path)
        try:
            tables = con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
            ).fetchall()
            names = {row[0] for row in tables}
            self.assertIn("inference_status", names)
        finally:
            con.close()

    def test_can_use_after_init(self):
        from persistence.duckdb_connection import get_connection
        from persistence.duckdb_init import initialize_database

        initialize_database(db_path=self.db_path)
        con = get_connection(self.db_path)
        try:
            set_status(con, "ex1", "exemplar", STAGE_CODE, PENDING)
            set_status(con, "ex2", "exemplar", STAGE_CODE, GENERATED)
            items = get_pending_items(con, STAGE_CODE)
            self.assertEqual(items, ["ex1"])
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
