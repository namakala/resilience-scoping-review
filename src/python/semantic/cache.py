"""In-memory BM25 index cache.

Shared across persistence and index builder. Use module-level variables
directly; this is effectively internal singleton state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from utils.logging import get_logger

logger = get_logger(__name__)

_CACHED_INDEX: Optional[dict] = None
_CACHED_PATH: Optional[Path] = None


def clear_cache() -> None:
    """Clear in-memory BM25 index cache."""
    global _CACHED_INDEX, _CACHED_PATH
    _CACHED_INDEX = None
    _CACHED_PATH = None
    logger.debug("BM25 index cache cleared")
