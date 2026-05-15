"""Tests for utils/atomic_io.py — atomic_write, write_json, write_csv."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from utils.atomic_io import atomic_write, write_csv, write_json

# ── atomic_write ─────────────────────────────────────────────────────


def test_atomic_write_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.txt"
        atomic_write("hello", path)
        assert path.read_text() == "hello"
        atomic_write("hello", path)
        assert path.read_text() == "hello"


def test_atomic_write_binary():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.bin"
        data = b"\x00\x01\x02"
        atomic_write(data, path, mode="wb")
        assert path.read_bytes() == data


def test_atomic_write_crash_cleanup():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.txt"
        tmp_files_before = set(os.listdir(tmp))
        try:
            atomic_write(42, path)  # will fail
        except TypeError:
            pass
        tmp_files_after = set(os.listdir(tmp))
        assert tmp_files_before == tmp_files_after


# ── write_json ───────────────────────────────────────────────────────


def test_write_json_creates_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.json"
        data = {"a": 1, "b": [2, 3]}
        write_json(data, path)
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded == data


def test_write_json_indent():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.json"
        write_json({"x": 1}, path, indent=4)
        text = path.read_text()
        assert text.startswith("{\n    ")


# ── write_csv ────────────────────────────────────────────────────────


def test_write_csv_writes_header():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.csv"
        rows = [{"name": "Alice", "age": "30"}]
        write_csv(rows, ["name", "age"], path)
        text = path.read_text()
        assert "name,age" in text


def test_write_csv_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.csv"
        rows = [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]
        write_csv(rows, ["a", "b"], path)
        text = path.read_text()
        assert "1,2" in text
        assert "3,4" in text
        assert text.count("\n") == 3  # header + 2 data rows
