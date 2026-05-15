"""Persistence: save/load BM25 index to disk with atomic writes and caching.

Orchestration-layer concern — the Hamilton DAG never calls these directly.
"""

import os
from pathlib import Path
from typing import Optional

import numpy as np
from utils.logging import get_logger

from . import cache
from .exceptions import BM25IndexError
from .tokenizer import _TOKENIZER

logger = get_logger(__name__)

PICKLE_PROTOCOL = __import__("pickle").HIGHEST_PROTOCOL
_DEFAULT_INDEX_FILENAME = "bm25_index.pkl"


def _resolve_index_path(override: Optional[Path | str] = None) -> Path:
    """Resolve the BM25 index file path.

    Priority: override → ``PROCESSED_DATA_PATH`` env + filename → default.
    """
    if override is not None:
        return Path(override)
    return (
        Path(os.getenv("PROCESSED_DATA_PATH", "data/processed"))
        / _DEFAULT_INDEX_FILENAME
    )


def save_bm25(path: Path | str, bm25_data: dict) -> None:
    """Serialize BM25 index to pickle with atomic write + round-trip check.

    Writes to a ``.tmp`` file first, then renames atomically.  Performs a
    round-trip sanity check when a BM25 object is present.

    Raises:
        BM25IndexError: If serialization or round-trip check fails.
    """
    path = Path(path)
    tmp_path = path.with_suffix(".tmp")

    try:
        with open(tmp_path, "wb") as f:
            __import__("pickle").dump(bm25_data, f, protocol=PICKLE_PROTOCOL)

        bm25_obj = bm25_data.get("bm25_object")
        if bm25_obj is not None:
            with open(tmp_path, "rb") as f:
                loaded = __import__("pickle").load(f)
            original_scores = bm25_obj.get_scores(_TOKENIZER("test"))
            loaded_scores = loaded["bm25_object"].get_scores(_TOKENIZER("test"))
            if not np.allclose(original_scores, loaded_scores, atol=1e-6):
                raise BM25IndexError("Round-trip score mismatch detected")

        tmp_path.rename(path)
        logger.info(
            "BM25 index saved",
            extra={
                "path": str(path),
                "size_mb": round(path.stat().st_size / 1024**2, 2),
            },
        )
    except Exception as e:
        if tmp_path.exists():
            tmp_path.unlink()
        raise BM25IndexError(f"Serialization error: {e}") from e


def load_bm25(
    path: Path | str | None = None,
) -> Optional[dict]:
    """Load BM25 index from a pickle file with schema validation.

    Caches the loaded index in memory.  Subsequent calls with the same
    path return the cached object.

    Raises:
        FileNotFoundError: If the index file does not exist.
        BM25IndexError: If deserialization or schema validation fails.
    """
    path = _resolve_index_path(path)

    if cache._CACHED_INDEX is not None and cache._CACHED_PATH == path:
        return cache._CACHED_INDEX

    if not path.exists():
        raise FileNotFoundError(f"BM25 index not found: {path}")

    try:
        with open(path, "rb") as f:
            data = __import__("pickle").load(f)
    except Exception as e:
        raise BM25IndexError(f"Pickle load error: {e}") from e

    if not isinstance(data, dict):
        raise BM25IndexError(f"Invalid BM25 data: expected dict, got {type(data)}")
    required = {"metadata", "corpus", "bm25_object", "entity_map"}
    if missing := required - data.keys():
        raise BM25IndexError(f"Invalid BM25 data: missing keys {missing}")

    cache._CACHED_INDEX = data
    cache._CACHED_PATH = path
    logger.info(
        "BM25 index loaded",
        extra={
            "path": str(path),
            "corpus_size": len(data["corpus"]),
        },
    )
    return data
