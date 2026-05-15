"""Tests for orchestration.hash_utils — file hashing and ingest guardrail."""

# flake8: noqa: E402
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent / "src" / "python")
)  # noqa: E402

from orchestration.hash_utils import (
    check_ingest_allowed,
    compute_file_hash,
    record_ingest_hashes,
)


class TestComputeFileHash(unittest.TestCase):
    """Tests for compute_file_hash — deterministic SHA-256 computation."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _write(self, name: str, content: str) -> Path:
        p = self.tmp / name
        p.write_text(content)
        return p

    def test_known_hash(self) -> None:
        """SHA-256 of 'hello' is known."""
        f = self._write("test.txt", "hello")
        expected = "2cf24dba5fb0a30e26e83b2ac5b9e29e" "1b161e5c1fa7425e73043362938b9824"
        self.assertEqual(compute_file_hash(f), expected)

    def test_different_files_different_hashes(self) -> None:
        f1 = self._write("a.txt", "content A")
        f2 = self._write("b.txt", "content B")
        self.assertNotEqual(compute_file_hash(f1), compute_file_hash(f2))

    def test_deterministic(self) -> None:
        f = self._write("test.txt", "same content")
        self.assertEqual(compute_file_hash(f), compute_file_hash(f))

    def test_empty_file(self) -> None:
        f = self._write("empty.txt", "")
        expected = "e3b0c44298fc1c149afbf4c8996fb924" "27ae41e4649b934ca495991b7852b855"
        self.assertEqual(compute_file_hash(f), expected)


class FakeConnection:
    """Minimal DuckDB connection mock for guardrail tests."""

    def __init__(self) -> None:
        self._state: dict = {}

    def execute(self, query: str, params: list | None = None) -> list:
        from unittest.mock import MagicMock

        row = MagicMock()
        if "SELECT" in query.upper():
            if self._state:
                import json

                row.fetchone.return_value = [json.dumps(self._state)]
            else:
                row.fetchone.return_value = None
        elif "INSERT OR REPLACE" in query.upper():
            import json

            self._state = json.loads(params[1]) if params else {}
        return row


class TestCheckIngestAllowed(unittest.TestCase):
    """Tests for check_ingest_allowed — ingest guardrail logic."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.data_path = self.tmp / "data.csv"
        self.tags_path = self.tmp / "tags.csv"
        self.data_path.write_text("id,content\n1,test")
        self.tags_path.write_text("tag,description\nroot,root tag")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_first_ingest_allowed(self) -> None:
        """No stored hashes → always allowed."""
        con = FakeConnection()
        self.assertTrue(check_ingest_allowed(con, self.data_path, self.tags_path))

    def test_unchanged_data_denied(self) -> None:
        """Hashes match → denied."""
        con = FakeConnection()
        record_ingest_hashes(con, self.data_path, self.tags_path)
        self.assertFalse(check_ingest_allowed(con, self.data_path, self.tags_path))

    def test_changed_data_allowed(self) -> None:
        """Data changed → allowed."""
        con = FakeConnection()
        record_ingest_hashes(con, self.data_path, self.tags_path)
        # Modify data file
        self.data_path.write_text("id,content\n1,changed")
        self.assertTrue(check_ingest_allowed(con, self.data_path, self.tags_path))

    def test_denied_message_on_stdout(self) -> None:
        """Denied message is printed when hashes match."""
        con = FakeConnection()
        record_ingest_hashes(con, self.data_path, self.tags_path)

        import io
        from unittest.mock import patch

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            result = check_ingest_allowed(con, self.data_path, self.tags_path)
            self.assertFalse(result)
            output = mock_out.getvalue()
            self.assertIn("Request Denied", output)
            self.assertIn("No changes detected", output)


class TestRecordIngestHashes(unittest.TestCase):
    """Tests for record_ingest_hashes — hash persistence."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.data_path = self.tmp / "data.csv"
        self.tags_path = self.tmp / "tags.csv"
        self.data_path.write_text("some data")
        self.tags_path.write_text("some tags")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_stores_hashes(self) -> None:
        con = FakeConnection()
        record_ingest_hashes(con, self.data_path, self.tags_path)
        self.assertIn("data_content_hash", con._state)
        self.assertIn("tags_content_hash", con._state)

    def test_hashes_are_deterministic(self) -> None:
        con1 = FakeConnection()
        con2 = FakeConnection()
        record_ingest_hashes(con1, self.data_path, self.tags_path)
        record_ingest_hashes(con2, self.data_path, self.tags_path)
        self.assertEqual(
            con1._state["data_content_hash"],
            con2._state["data_content_hash"],
        )
        self.assertEqual(
            con1._state["tags_content_hash"],
            con2._state["tags_content_hash"],
        )


if __name__ == "__main__":
    unittest.main()
