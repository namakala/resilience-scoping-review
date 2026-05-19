"""File content hashing for ingest guardrail.

SHA-256 content hashing prevents accidental re-ingest of unchanged data.
Hashes stored in DuckDB session state under ``data_content_hash`` and
``tags_content_hash`` keys.
"""

import hashlib
from pathlib import Path

import duckdb

# chunk size for streaming hash computation (64 KB)
_CHUNK_SIZE = 65536


def compute_file_hash(path: Path) -> str:
    """Compute SHA-256 hex digest of *path* contents.

    Args:
        path: Path to the file to hash.

    Returns:
        Hex-encoded SHA-256 digest (64 characters).
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_state(con: duckdb.DuckDBPyConnection) -> dict:
    """Load workflow state dict from DuckDB session_state table."""
    try:
        row = con.execute(
            "SELECT value FROM session_state WHERE key = 'workflow'"
        ).fetchone()
    except duckdb.Error:
        return {}
    if row is None or row[0] is None:
        return {}
    import json

    try:
        return dict(json.loads(row[0]))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _save_state(con: duckdb.DuckDBPyConnection, state: dict) -> None:
    """Persist workflow state dict to DuckDB session_state table."""
    import json

    payload = json.dumps(state)
    try:
        con.execute(
            "INSERT OR REPLACE INTO session_state (key, value) VALUES (?, ?)",
            ["workflow", payload],
        )
    except duckdb.Error:
        pass


def check_ingest_allowed(
    con: duckdb.DuckDBPyConnection, data_path: Path, tags_path: Path
) -> bool:
    """Check whether ingest should proceed based on content hashes.

    Compares current file hashes against stored hashes in session state.
    If hashes match, prints a denial message and returns ``False``.

    Args:
        con: Active DuckDB connection (existing or freshly opened).
        data_path: Path to exemplars CSV.
        tags_path: Path to tags CSV.

    Returns:
        ``True`` if ingest should proceed, ``False`` if blocked.
    """
    state = _load_state(con)
    stored_data_hash = state.get("data_content_hash")
    stored_tags_hash = state.get("tags_content_hash")

    # No stored hashes → first ingest, always allowed
    if not stored_data_hash and not stored_tags_hash:
        return True

    current_data_hash = compute_file_hash(data_path)
    current_tags_hash = compute_file_hash(tags_path)

    if current_data_hash == stored_data_hash and current_tags_hash == stored_tags_hash:
        print(
            "Request Denied: No changes detected on ingested data. "
            "Update data.csv or tags.csv before re-ingesting."
        )
        return False

    return True


def record_ingest_hashes(
    con: duckdb.DuckDBPyConnection, data_path: Path, tags_path: Path
) -> None:
    """Store current file hashes in session state after successful ingest.

    Args:
        con: Active DuckDB connection.
        data_path: Path to exemplars CSV.
        tags_path: Path to tags CSV.
    """
    state = _load_state(con)
    state["data_content_hash"] = compute_file_hash(data_path)
    state["tags_content_hash"] = compute_file_hash(tags_path)
    _save_state(con, state)


__all__ = [
    "compute_file_hash",
    "check_ingest_allowed",
    "record_ingest_hashes",
]
