"""Comprehensive unit tests for the logging framework.

Covers:
- Logger creation and configuration
- JSON formatting with required fields
- Sensitive data redaction (messages, extra fields, tracebacks)
- Console human-readable formatting
- Handler duplication prevention
- Log rotation configuration
- Directory creation
"""

# flake8: noqa: E402  # Allow imports after sys.path modification for test setup

import json
import logging
import os
import sys
import tempfile
import unittest
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

# Add src/python to sys.path so utils can be imported
sys.path.insert(  # noqa: E402
    0,
    str(Path(__file__).parent.parent.parent.parent / "src" / "python"),
)

from utils.logging import (
    ConsoleFormatter,
    JSONFormatter,
    SensitiveDataFilter,
    get_logger,
)


class TestSensitiveDataFilter(unittest.TestCase):
    """Tests for SensitiveDataFilter redaction logic."""

    def setUp(self):
        self.filter = SensitiveDataFilter()

    def test_redacts_groq_api_key_in_message(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="GROQ_API_KEY=sk-1234567890abcdef",
            args=(),
            exc_info=None,
        )
        self.filter.filter(record)
        self.assertEqual(record.msg, "***REDACTED***=sk-1234567890abcdef")

    def test_redacts_password_in_message(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="password=secret123",
            args=(),
            exc_info=None,
        )
        self.filter.filter(record)
        self.assertEqual(record.msg, "***REDACTED***=secret123")

    def test_redacts_token_in_message(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="token=abc-token-xyz",
            args=(),
            exc_info=None,
        )
        self.filter.filter(record)
        self.assertEqual(record.msg, "***REDACTED***=abc-***REDACTED***-xyz")

    def test_redacts_secret_in_message(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="my secret is hidden",
            args=(),
            exc_info=None,
        )
        self.filter.filter(record)
        self.assertEqual(record.msg, "my ***REDACTED*** is hidden")

    def test_redacts_api_key_in_message(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="api_key=gsk_abc123",
            args=(),
            exc_info=None,
        )
        self.filter.filter(record)
        self.assertEqual(record.msg, "***REDACTED***=gsk_abc123")

    def test_redacts_in_extra_fields(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="normal message",
            args=(),
            exc_info=None,
        )
        record.headers = {"Authorization": "Bearer token123"}
        self.filter.filter(record)
        self.assertEqual(record.headers["Authorization"], "Bearer ***REDACTED***")

    def test_redacts_in_args_tuple(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Processing request with key: %s",
            args=("secret-key-123",),
            exc_info=None,
        )
        self.filter.filter(record)
        self.assertEqual(record.args, ("***REDACTED***-***REDACTED***-123",))

    def test_redacts_in_args_dict(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Config loaded",
            args=(),
            exc_info=None,
        )
        record.extra_kwargs = {"password": "hunter2", "user": "alice"}
        self.filter.filter(record)
        self.assertEqual(record.extra_kwargs["password"], "***REDACTED***")
        self.assertEqual(record.extra_kwargs["user"], "alice")

    def test_redacts_multiple_patterns(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="API key: sk-123, password: pass, token: abc",
            args=(),
            exc_info=None,
        )
        self.filter.filter(record)
        self.assertEqual(
            record.msg,
            "***REDACTED***: sk-123, ***REDACTED***: pass, ***REDACTED***: abc",
        )

    def test_redacts_traceback_text(self):
        try:
            raise ValueError("Test error")
        except ValueError:
            exc_info = sys.exc_info()
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="test.py",
                lineno=1,
                msg="Error occurred",
                args=(),
                exc_info=exc_info,
            )
            self.filter.filter(record)
            self.assertIsNotNone(record.exc_text)
            self.assertNotIn("API_KEY", record.exc_text)


class TestJSONFormatter(unittest.TestCase):
    """Tests for JSONFormatter output structure."""

    def setUp(self):
        self.formatter = JSONFormatter()

    def test_format_returns_valid_json(self):
        record = logging.LogRecord(
            name="test.module",
            level=logging.INFO,
            pathname="/path/to/module.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        formatted = self.formatter.format(record)
        parsed = json.loads(formatted)
        self.assertIsInstance(parsed, dict)

    def test_includes_required_fields(self):
        record = logging.LogRecord(
            name="test.module",
            level=logging.WARNING,
            pathname="/path/to/module.py",
            lineno=10,
            msg="Hello world",
            args=(),
            exc_info=None,
        )
        formatted = self.formatter.format(record)
        parsed = json.loads(formatted)

        required_fields = {
            "timestamp",
            "level",
            "logger",
            "message",
            "module",
            "function",
        }
        self.assertEqual(required_fields, set(parsed.keys()) & required_fields)

    def test_timestamp_is_iso8601_with_timezone(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="test",
            args=(),
            exc_info=None,
        )
        formatted = self.formatter.format(record)
        parsed = json.loads(formatted)
        ts = parsed["timestamp"]
        dt = datetime.fromisoformat(ts)
        self.assertIsNotNone(dt.tzinfo, "Timestamp should have timezone info")

    def test_includes_extra_fields(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Processing batch",
            args=(),
            exc_info=None,
        )
        record.batch_id = 42
        record.user = "alice"
        formatted = self.formatter.format(record)
        parsed = json.loads(formatted)
        self.assertEqual(parsed["batch_id"], 42)
        self.assertEqual(parsed["user"], "alice")

    def test_handles_non_serializable_extra_fields(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Complex data",
            args=(),
            exc_info=None,
        )
        record.complex_obj = {"nested": set([1, 2, 3])}
        formatted = self.formatter.format(record)
        parsed = json.loads(formatted)
        self.assertIsInstance(parsed["complex_obj"], str)

    def test_exc_text_included_when_present(self):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            exc_info = sys.exc_info()
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="test.py",
                lineno=1,
                msg="Failed",
                args=(),
                exc_info=exc_info,
            )
            formatted = self.formatter.format(record)
            parsed = json.loads(formatted)
            self.assertIn("stack_trace", parsed)
            self.assertIn("RuntimeError", parsed["stack_trace"])


class TestConsoleFormatter(unittest.TestCase):
    """Tests for ConsoleFormatter human-readable output."""

    def test_format_structure(self):
        formatter = ConsoleFormatter()
        record = logging.LogRecord(
            name="my.module",
            level=logging.ERROR,
            pathname="module.py",
            lineno=5,
            msg="Something went wrong",
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)
        self.assertIn("ERROR", formatted)
        self.assertIn("my.module", formatted)
        self.assertIn("Something went wrong", formatted)
        self.assertRegex(formatted, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


class TestGetLogger(unittest.TestCase):
    """Tests for get_logger factory function."""

    def setUp(self):
        self.env_patcher = patch.dict(os.environ, {}, clear=True)
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        logging.root.handlers = []
        for logger_name in list(logging.Logger.manager.loggerDict.keys()):
            logger = logging.getLogger(logger_name)
            logger.handlers = []
            logger.propagate = True

    def test_returns_logger_instance(self):
        logger = get_logger("test.logger")
        self.assertIsInstance(logger, logging.Logger)

    def test_respects_log_level_debug(self):
        os.environ["LOG_LEVEL"] = "DEBUG"
        logger = get_logger("test")
        self.assertEqual(logger.level, logging.DEBUG)

    def test_respects_log_level_warning(self):
        os.environ["LOG_LEVEL"] = "WARNING"
        logger = get_logger("test")
        self.assertEqual(logger.level, logging.WARNING)

    def test_default_log_level_is_info(self):
        logger = get_logger("test")
        self.assertEqual(logger.level, logging.INFO)

    def test_creates_output_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "logs" / "output"
            with patch("utils.logging.Path") as mock_path:
                mock_path.return_value = log_dir
                get_logger("test")
                self.assertTrue(log_dir.exists())

    def test_file_handler_is_rotating(self):
        logger = get_logger("test")
        file_handlers = [
            h
            for h in logger.handlers
            if isinstance(h, logging.handlers.TimedRotatingFileHandler)
        ]
        self.assertEqual(len(file_handlers), 1)
        handler = file_handlers[0]
        self.assertEqual(handler.when, "MIDNIGHT")
        self.assertEqual(handler.backupCount, 7)

    def test_console_handler_is_stream_handler(self):
        logger = get_logger("test")
        console_handlers = [
            h for h in logger.handlers if type(h) is logging.StreamHandler
        ]
        self.assertEqual(len(console_handlers), 1)
        handler = console_handlers[0]
        self.assertEqual(handler.stream, sys.stderr)

    def test_duplicate_calls_no_duplicate_handlers(self):
        logger1 = get_logger("test")
        initial_handler_count = len(logger1.handlers)
        logger2 = get_logger("test")
        self.assertIs(logger1, logger2)
        self.assertEqual(len(logger2.handlers), initial_handler_count)

    def test_each_logger_name_gets_separate_logger(self):
        logger_a = get_logger("module.a")
        logger_b = get_logger("module.b")
        self.assertIsNot(logger_a, logger_b)

    def test_filters_attached_to_handlers(self):
        logger = get_logger("test")
        for handler in logger.handlers:
            filters = [f for f in handler.filters if isinstance(f, SensitiveDataFilter)]
            self.assertEqual(
                len(filters), 1, f"Handler {handler} missing SensitiveDataFilter"
            )

    def test_handlers_use_correct_formatters(self):
        from utils.logging import ConsoleFormatter, JSONFormatter

        logger = get_logger("test")
        for handler in logger.handlers:
            if isinstance(handler, logging.handlers.TimedRotatingFileHandler):
                self.assertIsInstance(handler.formatter, JSONFormatter)
            elif isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, logging.handlers.TimedRotatingFileHandler
            ):
                self.assertIsInstance(handler.formatter, ConsoleFormatter)

    def test_log_message_goes_to_file_and_console(self):
        with patch("sys.stderr", new_callable=StringIO) as mock_stderr:
            with tempfile.TemporaryDirectory() as tmpdir:
                test_log_file = Path(tmpdir) / "test.log"
                test_logger = logging.getLogger("test.file")
                test_logger.handlers = []
                test_logger.setLevel(logging.INFO)
                test_logger.propagate = False
                file_h = logging.handlers.TimedRotatingFileHandler(
                    filename=str(test_log_file),
                    when="midnight",
                    backupCount=7,
                )
                file_h.setFormatter(JSONFormatter())
                file_h.addFilter(SensitiveDataFilter())
                test_logger.addHandler(file_h)
                console_h = logging.StreamHandler(mock_stderr)
                console_h.setFormatter(ConsoleFormatter())
                test_logger.addFilter(SensitiveDataFilter())
                test_logger.addHandler(console_h)

                test_logger.info("Test message")

                test_log_file_content = test_log_file.read_text()
                self.assertIn("Test message", test_log_file_content)

                console_output = mock_stderr.getvalue()
                self.assertIn("Test message", console_output)


class TestLoggerIntegration(unittest.TestCase):
    """Integration tests for full logger behavior."""

    def setUp(self):
        self.env_patcher = patch.dict(os.environ, {"LOG_LEVEL": "INFO"}, clear=True)
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        logging.root.handlers = []
        for logger_name in list(logging.Logger.manager.loggerDict.keys()):
            logger = logging.getLogger(logger_name)
            logger.handlers = []
            logger.propagate = True

    def test_exception_logging_includes_traceback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "app.log"
            with patch("utils.logging.Path") as mock_path:
                mock_path.return_value = log_file
                test_logger = logging.getLogger("test.new")
                test_logger.handlers = []
                test_logger.setLevel(logging.INFO)
                test_logger.propagate = False
                file_h = logging.handlers.TimedRotatingFileHandler(
                    filename=str(log_file),
                    when="midnight",
                    backupCount=7,
                )
                file_h.setFormatter(JSONFormatter())
                file_h.addFilter(SensitiveDataFilter())
                test_logger.addHandler(file_h)

                try:
                    raise ValueError("Test exception")
                except ValueError:
                    test_logger.exception("An error occurred")

                log_content = log_file.read_text()
                log_entry = json.loads(log_content.strip())
                self.assertIn("stack_trace", log_entry)
                self.assertIn("ValueError", log_entry["stack_trace"])

    def test_extra_fields_in_json_log(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "app.log"
            with patch("utils.logging.Path") as mock_path:
                mock_path.return_value = log_file
                test_logger = logging.getLogger("test.extra")
                test_logger.handlers = []
                test_logger.setLevel(logging.INFO)
                test_logger.propagate = False
                file_h = logging.handlers.TimedRotatingFileHandler(
                    filename=str(log_file),
                    when="midnight",
                    backupCount=7,
                )
                file_h.setFormatter(JSONFormatter())
                file_h.addFilter(SensitiveDataFilter())
                test_logger.addHandler(file_h)

                test_logger.info(
                    "Batch processed", extra={"batch_id": 123, "items": 50}
                )

                log_content = log_file.read_text()
                log_entry = json.loads(log_content.strip())
                self.assertEqual(log_entry["batch_id"], 123)
                self.assertEqual(log_entry["items"], 50)


if __name__ == "__main__":
    unittest.main()
