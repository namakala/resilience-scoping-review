"""Centralized structured logging with JSON formatting and sensitive data filtering."""

import contextlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Iterator

# Sensitive data patterns to redact (case-insensitive, word boundaries).
# Ordered from most-specific to least-specific to avoid partial matches.
_SENSITIVE_PATTERNS = [
    re.compile(r"\bapi[_\s-]?key\b", re.IGNORECASE),  # "api key", "api-key", "api_key"
    re.compile(r"\bgroq_api_key\b", re.IGNORECASE),
    re.compile(r"\bpassword\b", re.IGNORECASE),
    re.compile(r"\btoken\w*\b", re.IGNORECASE),  # token, token123, tokenXYZ
    re.compile(r"\bsecret\b", re.IGNORECASE),
    re.compile(r"\bapi_key\b", re.IGNORECASE),
    re.compile(r"\bkey\b", re.IGNORECASE),
]

_REDACTION_PLACEHOLDER = "***REDACTED***"

# Standard LogRecord attributes to exclude from JSON output
_RESERVED_ATTRS = frozenset(
    [
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "taskName",
    ]
)


class SensitiveDataFilter(logging.Filter):
    """Redacts sensitive data from log records."""

    def _redact_string(self, text: Any) -> Any:
        if not isinstance(text, str):
            return text
        result = text
        for pattern in _SENSITIVE_PATTERNS:
            result = pattern.sub(_REDACTION_PLACEHOLDER, result)
        return result

    def _redact_value(self, value: Any, key_is_sensitive: bool = False) -> Any:
        """Recursively redact; replace entire value if key is sensitive."""
        if key_is_sensitive:
            return _REDACTION_PLACEHOLDER
        if isinstance(value, str):
            return self._redact_string(value)
        elif isinstance(value, dict):
            return {
                k: self._redact_value(v, any(p.search(k) for p in _SENSITIVE_PATTERNS))
                for k, v in value.items()
            }
        elif isinstance(value, list):
            return [self._redact_value(v) for v in value]
        elif isinstance(value, tuple):
            return tuple(self._redact_value(v) for v in value)
        else:
            return value

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact the main message
        record.msg = self._redact_string(record.msg)

        # Redact args
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self._redact_value(
                        v, any(p.search(k) for p in _SENSITIVE_PATTERNS)
                    )
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(self._redact_value(v) for v in record.args)

        # Redact attributes in __dict__ recursively
        for key, value in list(record.__dict__.items()):
            redacted = self._redact_value(value)
            setattr(record, key, redacted)

        # Ensure exception text is available and redacted
        if record.exc_info and not record.exc_text:
            formatter = logging.Formatter()
            record.exc_text = formatter.formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = self._redact_string(record.exc_text)

        return True


class JSONFormatter(logging.Formatter):
    """Formats log records as structured JSON."""

    def format(self, record: logging.LogRecord) -> str:
        # Ensure exception text is available
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)

        payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
        }

        if record.exc_text:
            payload["stack_trace"] = record.exc_text

        # Add extra fields (non-reserved)
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and not key.startswith("_"):
                try:
                    json.dumps(value)
                    payload[key] = value
                except (TypeError, OverflowError):
                    payload[key] = str(value)

        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """Human-readable console formatter for development."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger with JSON file and console output.

    Args:
        name: Logger name, typically __name__ of calling module.

    Returns:
        Logger instance with rotating file and console handlers.
    """
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    logger.propagate = False

    if logger.handlers:
        return logger

    log_dir = Path("data/output")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "app.log"

    file_handler = TimedRotatingFileHandler(
        filename=str(log_path),
        when="midnight",
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(JSONFormatter())
    file_handler.addFilter(SensitiveDataFilter())

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(ConsoleFormatter())
    console_handler.addFilter(SensitiveDataFilter())

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


@contextlib.contextmanager
def suppress_stderr_logging() -> Iterator[None]:
    """Temporarily suppress all stderr logging handlers.

    Removes every ``StreamHandler`` whose stream is ``sys.stderr``
    (or ``sys.__stderr__``) from the root logger and all named loggers.
    Restores them on exit.  Intended for wrapping TUI sessions where
    raw stderr output would corrupt Textual's alternate screen.
    """
    stashed: list[tuple[logging.Logger, logging.Handler]] = []

    def _suppress() -> None:
        nonlocal stashed
        for logger_name in list(logging.root.manager.loggerDict):
            logger = logging.getLogger(logger_name)
            for handler in list(logger.handlers):
                if isinstance(handler, logging.StreamHandler) and handler.stream in (
                    sys.stderr,
                    sys.__stderr__,
                ):
                    stashed.append((logger, handler))
                    logger.removeHandler(handler)
        for handler in list(logging.root.handlers):
            if isinstance(handler, logging.StreamHandler) and handler.stream in (
                sys.stderr,
                sys.__stderr__,
            ):
                stashed.append((logging.root, handler))
                logging.root.removeHandler(handler)

    def _restore() -> None:
        for logger, handler in stashed:
            logger.addHandler(handler)
        stashed.clear()

    _suppress()
    try:
        yield
    finally:
        _restore()
