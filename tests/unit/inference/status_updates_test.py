"""Tests for inference/status_updates.py — success/failure helpers."""

# flake8: noqa: E402
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src" / "python"))

from inference.status_updates import mark_failure, mark_success


class TestMarkSuccess(unittest.TestCase):
    """mark_success calls set_status with correct params."""

    def test_success_calls_set_status(self):
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        with patch("inference.status_updates.set_status") as mock_set:
            mark_success(con, 42, "exemplar", "code")
            mock_set.assert_called_once_with(
                con,
                entity_id="42",
                entity_type="exemplar",
                stage="code",
                status="generated",
            )


class TestMarkFailure(unittest.TestCase):
    """mark_failure logs error without changing status."""

    def test_failure_logs_error(self):
        con = MagicMock(spec=duckdb.DuckDBPyConnection)
        with patch("inference.status_updates.logger") as mock_log:
            mark_failure(con, 99, "some error")
            mock_log.error.assert_called_once()
            call_args = mock_log.error.call_args
            fmt, arg1, arg2 = call_args[0]
            self.assertEqual(arg1, 99)
            self.assertEqual(arg2, "some error")


if __name__ == "__main__":
    unittest.main()
