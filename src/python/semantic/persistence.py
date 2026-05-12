"""Persistence: save/load BM25 index to disk with atomic writes and caching."""

import os
from pathlib import Path
from typing import Dict, Optional

import numpy as np
from utils.logging import get_logger

from . import cache
from .corpus import _build_corpus_and_map, _compute_corpus_hash
from .exceptions import BM25IndexError, IndexCorruptedError
from .tokenizer import _TOKENIZER

logger = get_logger(__name__)

# Constants

PICKLE_PROTOCOL = __import__("pickle").HIGHEST_PROTOCOL
_DEFAULT_INDEX_FILENAME = "bm25_index.pkl"


# Path resolution


def _resolve_index_path(override: Optional[Path | str] = None) -> Path:
    """Resolve the BM25 index file path.

    Priority:
        1. If override is provided, use it.
        2. PROCESSED_DATA_PATH environment variable + 'bm25_index.pkl'.
        3. Default: data/processed/bm25_index.pkl

    Args:
        override: Explicit path argument.

    Returns:
        Path object for the index file.
    """
    if override is not None:
        return Path(override)
    return (
        Path(os.getenv("PROCESSED_DATA_PATH", "data/processed"))
        / _DEFAULT_INDEX_FILENAME
    )


# Serialization


def save_bm25(path: Path | str, bm25_data: Dict) -> None:
    """Serialize BM25 index to pickle file with metadata.

    Uses highest pickle protocol. Writes to temporary file first, then atomic
    rename to avoid corruption on interruption. Also performs round-trip sanity
    check to ensure scoring is preserved (skipped if bm25_object is None).

    Args:
        path: Destination file path.
        bm25_data: Dictionary containing metadata, corpus,
                   bm25_object, entity_map.

    Raises:
        BM25IndexError: If serialization or round-trip check fails.
    """
    path = Path(path)
    tmp_path = path.with_suffix(".tmp")

    try:
        with open(tmp_path, "wb") as f:
            __import__("pickle").dump(bm25_data, f, protocol=PICKLE_PROTOCOL)

        # Round-trip sanity check (only if BM25 object exists)
        bm25_obj = bm25_data.get("bm25_object")
        if bm25_obj is not None:
            test_query = "test"
            with open(tmp_path, "rb") as f:
                loaded = __import__("pickle").load(f)
            original_scores = bm25_obj.get_scores(_TOKENIZER(test_query))
            loaded_scores = loaded["bm25_object"].get_scores(_TOKENIZER(test_query))
            if not np.allclose(original_scores, loaded_scores, atol=1e-6):
                raise BM25IndexError("Round-trip score mismatch detected")

        tmp_path.rename(path)
        file_size = path.stat().st_size
        logger.info(
            "BM25 index saved",
            extra={
                "path": str(path),
                "size_mb": round(file_size / 1024**2, 2),
            },
        )
        if file_size > 100 * 1024 * 1024:
            logger.warning(
                "BM25 index size exceeds 100 MB",
                extra={"size_mb": file_size / 1024**2},
            )
    except Exception as e:
        if tmp_path.exists():
            tmp_path.unlink()
        logger.error("Save BM25 failed", extra={"error": str(e)})
        raise BM25IndexError(f"Serialization error: {e}") from e


def load_bm25(
    path: Path | str | None = None,
    _validate_against_corpus: bool = True,
) -> Optional[Dict]:
    """Load BM25 index from pickle file, validating corpus_hash.

    Caches the loaded index in memory. Subsequent calls return the
    cached object unless a different path is provided.

    Args:
        path: File path; defaults to PROCESSED_DATA_PATH/bm25_index.pkl.
        _validate_against_corpus: If True, recompute corpus_hash from current
            keywords and compare to stored hash. Set False during build to
            avoid infinite recursion.

    Returns:
        Dictionary with keys: metadata, corpus, bm25_object, entity_map.

    Raises:
        FileNotFoundError: If index file does not exist.
        IndexCorruptedError: If corpus_hash mismatch detected.
        BM25IndexError: For other load/validation failures.
    """
    path = _resolve_index_path(path)

    # Return cached if available and matching path
    if cache._CACHED_INDEX is not None and cache._CACHED_PATH == path:
        logger.debug("Returning cached BM25 index", extra={"path": str(path)})
        return cache._CACHED_INDEX

    if not path.exists():
        logger.error("BM25 index file not found", extra={"path": str(path)})
        raise FileNotFoundError(f"BM25 index not found: {path}")

    try:
        with open(path, "rb") as f:
            data = __import__("pickle").load(f)
    except Exception as e:
        logger.error("Failed to deserialize BM25 index", extra={"error": str(e)})
        raise BM25IndexError(f"Pickle load error: {e}") from e

    # Validate type and schema
    if not isinstance(data, dict):
        raise BM25IndexError(f"Invalid BM25 data: expected dict, got {type(data)}")
    required = {"metadata", "corpus", "bm25_object", "entity_map"}
    if not required.issubset(data.keys()):
        missing = required - data.keys()
        raise BM25IndexError(f"Invalid BM25 data: missing keys {missing}")

    metadata = data["metadata"]
    stored_hash = metadata.get("corpus_hash")
    if stored_hash is None:
        raise BM25IndexError("Metadata missing corpus_hash")

    # Verify corpus_hash against current keywords
    if _validate_against_corpus:
        try:
            current_corpus, _ = _build_corpus_and_map()
            current_hash = _compute_corpus_hash(current_corpus)
            if current_hash != stored_hash:
                logger.error(
                    "Corpus hash mismatch: rebuild required",
                    extra={"stored": stored_hash, "current": current_hash},
                )
                raise IndexCorruptedError(
                    "BM25 index corpus_hash differs from current keywords; "
                    "re-run build_index() to rebuild."
                )
        except Exception as e:
            logger.error("Corpus validation failed", extra={"error": str(e)})
            raise

    # Cache and return
    cache._CACHED_INDEX = data
    cache._CACHED_PATH = path
    logger.info(
        "BM25 index loaded",
        extra={
            "path": str(path),
            "version": metadata.get("version"),
            "corpus_size": len(data["corpus"]),
        },
    )
    return data
