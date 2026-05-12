"""BM25 index builder – constructs the lexical index from keywords."""

import os
from datetime import datetime, timezone

from utils.logging import get_logger

from . import cache
from .corpus import _build_corpus_and_map, _compute_corpus_hash
from .exceptions import BM25IndexError
from .persistence import _resolve_index_path
from .persistence import load_bm25 as _load_bm25
from .persistence import save_bm25

logger = get_logger(__name__)

VERSION = "1.0"


def build_index(force_rebuild: bool = False) -> None:
    """Build BM25 index from keywords and save to configured path.

    Steps:
        1. Load keywords Parquet via _build_corpus_and_map.
        2. Compute corpus_hash for rebuild detection.
        3. Train BM25Okapi on corpus (skip if corpus empty — store None).
        4. Serialize with metadata via save_bm25().
        5. Update in-memory cache.

    Args:
        force_rebuild: If True, overwrite existing index even if up-to-date.

    Raises:
        BM25IndexError: If keywords missing/corrupted or save fails.
    """
    path = _resolve_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Check if we really need to rebuild
    if not force_rebuild and path.exists():
        try:
            # Skip corpus validation here to avoid recursion
            cached = _load_bm25(path, _validate_against_corpus=False)
            if cached is not None:
                logger.info("BM25 index already up-to-date; skipping build")
                return
        except Exception as e:
            logger.warning(
                "Failed to validate existing index; rebuilding", extra={"error": str(e)}
            )

    logger.info("Building BM25 index from keywords")

    try:
        corpus, entity_map = _build_corpus_and_map()
        corpus_hash = _compute_corpus_hash(corpus)
        from rank_bm25 import BM25Okapi

        bm25 = BM25Okapi(corpus) if corpus else None
    except Exception as e:
        logger.error("Failed to build BM25 corpus", extra={"error": str(e)})
        raise BM25IndexError(f"Corpus construction failed: {e}") from e

    metadata = {
        "version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus_hash": corpus_hash,
        "tokenizer_config": os.getenv(
            "BM25_TOKENIZER_CONFIG", "lowercase,split_by_space"
        ),
    }

    bm25_data = {
        "metadata": metadata,
        "corpus": corpus,
        "bm25_object": bm25,
        "entity_map": entity_map,
    }

    try:
        save_bm25(path, bm25_data)
        # Update in-memory cache via cache module
        cache._CACHED_INDEX = bm25_data
        cache._CACHED_PATH = path
        logger.info(
            "BM25 index built and saved",
            extra={
                "path": str(path),
                "docs": len(corpus),
                "exemplars": len(entity_map),
            },
        )
    except Exception as e:
        logger.error("Failed to save BM25 index", extra={"error": str(e)})
        raise BM25IndexError(f"Save failed: {e}") from e
