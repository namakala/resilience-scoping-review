"""Atomic file I/O — temp file then rename.

Provides generic ``write_json``, ``write_csv``, ``write_markdown``
that all delegate to ``atomic_write`` for crash-safe persistence.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write(data: str | bytes, path: Path, mode: str = "w") -> None:
    """Write *data* to *path* atomically via temp file then rename.

    On failure the temp file is cleaned up.  Supports text (default)
    and binary (``mode="wb"``) writes.
    """
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
    )
    try:
        if isinstance(data, str) and "b" not in mode:
            with os.fdopen(fd, mode, encoding="utf-8") as f:
                f.write(data)
        else:
            with os.fdopen(fd, mode) as f:
                f.write(data)
        os.rename(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def write_json(
    data: dict[str, Any],
    path: Path,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
    sort_keys: bool = True,
) -> None:
    """Serialize *data* as pretty-printed JSON and write atomically."""
    blob = json.dumps(
        data, indent=indent, ensure_ascii=ensure_ascii, sort_keys=sort_keys
    )
    atomic_write(blob, path)


def write_csv(
    rows: list[dict[str, str]],
    fieldnames: list[str],
    path: Path,
) -> None:
    """Write *rows* as CSV with header and write atomically."""
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        os.rename(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def write_markdown(text: str, path: Path) -> None:
    """Write Markdown text atomically."""
    atomic_write(text, path)


__all__ = [
    "atomic_write",
    "write_json",
    "write_csv",
    "write_markdown",
]
