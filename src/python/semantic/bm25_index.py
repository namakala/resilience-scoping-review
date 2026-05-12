"""BM25 lexical index with pickle-based persistence and configurable tokenization.

Builds index from keyword corpus (data/processed/keywords.parquet), serializes
with metadata (version, timestamp, corpus_hash, tokenizer_config), and provides
normalized scoring API. Tokenizer pipeline configured via BM25_TOKENIZER_CONFIG.

References:
    ADR-006 (Retrieval Strategy): BM25 as lexical guardrail alongside embeddings.
"""

import hashlib
import os
import pickle
import string
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, cast

import numpy as np
import polars as pl
from rank_bm25 import BM25Okapi
from utils.logging import get_logger

logger = get_logger(__name__)

# ── Module-level cached index ────────────────────────────────────────────────

_CACHED_INDEX: Optional[Dict] = None
_CACHED_PATH: Optional[Path] = None

# ── Constants ────────────────────────────────────────────────────────────────

VERSION = "1.0"
PICKLE_PROTOCOL = pickle.HIGHEST_PROTOCOL

_DEFAULT_INDEX_PATH = "data/processed/bm25_index.pkl"

# Predefined stopword list (minimal built-in; no external deps)
_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "shall",
    "should",
    "can",
    "could",
    "may",
    "might",
    "must",
    "i",
    "you",
    "he",
    "she",
    "it",
    "we",
    "they",
    "this",
    "that",
    "these",
    "those",
    "my",
    "your",
    "his",
    "her",
    "its",
    "our",
    "their",
    "me",
    "him",
    "her",
    "us",
    "them",
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "where",
    "when",
    "why",
    "how",
    "not",
    "no",
    "yes",
    "so",
    "if",
    "then",
    "there",
    "here",
    "all",
    "some",
    "any",
    "each",
    "every",
    "both",
    "few",
    "many",
    "much",
    "more",
    "most",
    "other",
    "such",
    "only",
    "own",
    "same",
    "than",
    "too",
    "very",
    "just",
    "now",
    "then",
    "well",
    "also",
    "back",
    "up",
    "down",
    "out",
    "off",
    "over",
    "under",
    "again",
    "ever",
    "never",
    "always",
    "often",
    "sometimes",
    "enough",
    "even",
    "quite",
    "rather",
    "like",
    "as",
    "because",
    "since",
    "although",
    "though",
    "while",
    "unless",
    "until",
    "before",
    "after",
    "during",
    "about",
    "above",
    "below",
    "between",
    "among",
    "through",
    "throughout",
    "toward",
    "towards",
    "from",
    "into",
    "onto",
    "upon",
    "across",
    "along",
    "around",
    "round",
    "past",
    "via",
    "without",
    "within",
    "beyond",
    "beside",
    "besides",
    "concerning",
    "considering",
    "despite",
    "including",
    "regarding",
    "versus",
}

# Valid toggles for BM25_TOKENIZER_CONFIG
_VALID_TOGGLES = {"lowercase", "strip_punctuation", "split_by_space", "remove_stopword"}

# ── Public Exceptions ────────────────────────────────────────────────────────


class BM25IndexError(Exception):
    """Base exception for all BM25 index errors."""

    pass


class IndexCorruptedError(BM25IndexError):
    """Raised when stored index corpus_hash differs from current keywords."""

    pass


# ── Configuration Helpers ────────────────────────────────────────────────────


def _resolve_index_path(override: Optional[Path | str] = None) -> Path:
    """Resolve the BM25 index file path.

    Priority:
        1. If override is provided, use it.
        2. BM25_INDEX_PATH environment variable.
        3. Default: data/processed/bm25_index.pkl

    Args:
        override: Explicit path argument (used by save_bm25/load_bm25 callers).

    Returns:
        Path object for the index file.
    """
    if override is not None:
        return Path(override)
    return Path(os.getenv("BM25_INDEX_PATH", _DEFAULT_INDEX_PATH))


def _parse_tokenizer_config(config_str: Optional[str] = None) -> List[str]:
    """Parse comma-separated tokenizer config to ordered list of valid toggles.

    Args:
        config_str: e.g., "lowercase,split_by_space,remove_stopword".
            If None, reads BM25_TOKENIZER_CONFIG from env
            (default: "lowercase,split_by_space").

    Returns:
        List of toggle names in order of application.

    Raises:
        ValueError: if any toggle is not in _VALID_TOGGLES.
    """
    if config_str is None:
        config_str = os.getenv("BM25_TOKENIZER_CONFIG", "lowercase,split_by_space")
    toggles = [t.strip() for t in config_str.split(",") if t.strip()]
    for t in toggles:
        if t not in _VALID_TOGGLES:
            raise ValueError(
                f"Invalid tokenizer toggle '{t}'. "
                f"Valid toggles: {sorted(_VALID_TOGGLES)}"
            )
    return toggles


def _build_tokenizer(toggles: List[str]) -> Callable[[str], List[str]]:
    """Construct a tokenizer function from a pipeline of toggles.

    Order matters: toggles are applied sequentially. 'split_by_space' must
    appear exactly once and is the tokenization step (produces list of strings).

    Args:
        toggles: Ordered list of toggle names.

    Returns:
        Callable that takes raw keyword string and returns List[str] tokens.
    """
    if "split_by_space" not in toggles:
        raise ValueError("Tokenizer config must include 'split_by_space'")

    def tokenize(text: str) -> List[str]:
        # Apply toggles in order; text type changes during pipeline
        for toggle in toggles:
            if toggle == "lowercase":
                text = text.lower()  # type: ignore[assignment]
            elif toggle == "strip_punctuation":
                text = text.translate(  # type: ignore[assignment]
                    str.maketrans("", "", string.punctuation)
                )
            elif toggle == "split_by_space":
                text = text.split()  # type: ignore[assignment]
            elif toggle == "remove_stopword":
                # text is now a list if split_by_space already applied
                if isinstance(text, list):
                    text = [t for t in text if t not in _STOPWORDS]
                else:
                    # split_by_space not yet applied: split then filter
                    text = [  # type: ignore[assignment]
                        t for t in text.split() if t not in _STOPWORDS
                    ]
        return text if isinstance(text, list) else [text]

    return tokenize


# ── Tokenizer Pipeline ───────────────────────────────────────────────────────

# Initialize tokenizer at module load using environment configuration
_TOKENIZER_TOGGLES = _parse_tokenizer_config()
_TOKENIZER = _build_tokenizer(_TOKENIZER_TOGGLES)
logger.info(
    "BM25 tokenizer initialized",
    extra={"toggles": _TOKENIZER_TOGGLES},
)

# ── Corpus Building ──────────────────────────────────────────────────────────


def _load_keywords_lazy() -> pl.LazyFrame:
    """Lazy-load keywords.parquet using persistence loaders.

    Returns:
        LazyFrame with schema: keyword_id, exemplar_id, keyword_text, frequency.
    """
    from persistence.loaders import load_keywords  # deferred import to avoid cycles

    return load_keywords()


def _build_corpus_and_map() -> tuple[List[List[str]], Dict[int, int]]:
    """Construct tokenized corpus and exemplar_id→index map from keywords.

    Groups keywords by exemplar_id (ascending order), sorts keywords
    alphabetically within each exemplar, tokenizes via configured tokenizer.

    Returns:
        corpus: List of token lists, order = sorted exemplar_id ascending.
        entity_map: Dict mapping exemplar_id → corpus index.
    """
    lf = _load_keywords_lazy()
    df = lf.select(["exemplar_id", "keyword_text"]).collect()

    if df.height == 0:
        logger.warning("Keywords corpus is empty; building empty BM25 index")
        return [], {}

    # Group keywords by exemplar_id
    grouped = (
        df.group_by("exemplar_id")
        .agg(pl.col("keyword_text").sort())
        .sort("exemplar_id")
    )

    corpus: List[List[str]] = []
    entity_map: Dict[int, int] = {}

    for idx, row in enumerate(grouped.iter_rows()):
        exemplar_id = row[0]  # exemplar_id
        keyword_list = row[1]  # List[str] (already sorted)
        tokenized = _TOKENIZER(
            " ".join(keyword_list)
        )  # join then retokenize with pipeline
        corpus.append(tokenized)
        entity_map[exemplar_id] = idx

    logger.info(
        "Corpus built",
        extra={"documents": len(corpus), "vocab_exemplars": len(entity_map)},
    )
    return corpus, entity_map


def _compute_corpus_hash(corpus: List[List[str]]) -> str:
    """Compute deterministic SHA256 hash of the corpus for rebuild detection.

    Strategy: for each exemplar's sorted keywords, join with ':' -> concatenate
    all exemplar strings with '|' using exemplar_id ascending order.

    Args:
        corpus: List of token lists (deterministic order).

    Returns:
        First 16 hex characters of SHA256 digest.
    """
    if not corpus:
        return hashlib.sha256(b"<empty>").hexdigest()[:16]

    # Reconstruct per-exemplar sorted keyword strings (already sorted in corpus)
    parts = []
    for doc in corpus:
        # Sort tokens alphabetically for hash stability (already
        # lowercase/preprocessed from tokenizer)
        sorted_tokens = sorted(doc)
        parts.append(":".join(sorted_tokens))
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


# ── Index Building ───────────────────────────────────────────────────────────


def build_index(force_rebuild: bool = False) -> None:
    """Build BM25 index from keywords and save to configured path.

    Steps:
        1. Load keywords Parquet via lazy loader.
        2. Build tokenized corpus (exemplar_id ascending) and entity_map.
        3. Compute corpus_hash for rebuild detection.
        4. Train BM25Okapi on corpus (skip if corpus empty — store None).
        5. Serialize with metadata via save_bm25().

    Args:
        force_rebuild: If True, overwrite existing index even if up-to-date.

    Raises:
        BM25IndexError: If keywords missing/corrupted or save fails.
    """
    global _CACHED_INDEX, _CACHED_PATH

    path = _resolve_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Check if we really need to rebuild
    if not force_rebuild and path.exists():
        try:
            cached = load_bm25(path, _validate_against_corpus=False)
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
        # Cache in memory after successful save
        _CACHED_INDEX = bm25_data
        _CACHED_PATH = path
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


# ── Persistence ───────────────────────────────────────────────────────────────


def save_bm25(path: Path | str, bm25_data: Dict) -> None:
    """Serialize BM25 index to pickle file with metadata.

    Uses highest pickle protocol. Writes to temporary file first, then atomic
    rename to avoid corruption on interruption. Also performs round-trip sanity
    check to ensure scoring is preserved (skipped if bm25_object is None).

    Args:
        path: Destination file path.
        bm25_data: Dictionary containing metadata, corpus, bm25_object, entity_map.

    Raises:
        BM25IndexError: If serialization or round-trip check fails.
    """
    path = Path(path)
    tmp_path = path.with_suffix(".tmp")

    try:
        with open(tmp_path, "wb") as f:
            pickle.dump(bm25_data, f, protocol=PICKLE_PROTOCOL)

        # Round-trip sanity check (only if BM25 object exists)
        bm25_obj = bm25_data.get("bm25_object")
        if bm25_obj is not None:
            test_query = "test"
            with open(tmp_path, "rb") as f:
                loaded = pickle.load(f)
            original_scores = bm25_obj.get_scores(_TOKENIZER(test_query))
            loaded_scores = loaded["bm25_object"].get_scores(_TOKENIZER(test_query))
            if not np.allclose(original_scores, loaded_scores, atol=1e-6):
                raise BM25IndexError("Round-trip score mismatch detected")

        tmp_path.rename(path)
        file_size = path.stat().st_size
        logger.info(
            "BM25 index saved",
            extra={"path": str(path), "size_mb": round(file_size / 1024**2, 2)},
        )
        if file_size > 100 * 1024 * 1024:
            logger.warning(
                "BM25 index size exceeds 100 MB", extra={"size_mb": file_size / 1024**2}
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

    Caches the loaded index in memory. Subsequent calls return the cached object
    unless a different path is provided.

    Args:
        path: File path; defaults to BM25_INDEX_PATH env var.
        _validate_against_corpus: If True, recompute corpus_hash from current
            keywords and compare to stored hash. Set False during build to avoid
            infinite recursion (when keywords may not yet be stable).

    Returns:
        Dictionary with keys: metadata, corpus, bm25_object, entity_map.

    Raises:
        FileNotFoundError: If index file does not exist.
        IndexCorruptedError: If corpus_hash mismatch detected.
        BM25IndexError: For other load/validation failures.
    """
    global _CACHED_INDEX, _CACHED_PATH

    path = _resolve_index_path(path)

    # Return cached if available and matching path
    if _CACHED_INDEX is not None and _CACHED_PATH == path:
        logger.debug("Returning cached BM25 index", extra={"path": str(path)})
        return _CACHED_INDEX

    if not path.exists():
        logger.error("BM25 index file not found", extra={"path": str(path)})
        raise FileNotFoundError(f"BM25 index not found: {path}")

    try:
        with open(path, "rb") as f:
            data = pickle.load(f)
    except Exception as e:
        logger.error("Failed to deserialize BM25 index", extra={"error": str(e)})
        raise BM25IndexError(f"Pickle load error: {e}") from e

    # Validate type
    if not isinstance(data, dict):
        raise BM25IndexError(f"Invalid BM25 data: expected dict, got {type(data)}")

    # Validate schema
    required = {"metadata", "corpus", "bm25_object", "entity_map"}
    if not required.issubset(data.keys()):
        missing = required - data.keys()
        raise BM25IndexError(f"Invalid BM25 data: missing keys {missing}")

    metadata = data["metadata"]
    stored_hash = metadata.get("corpus_hash")
    if stored_hash is None:
        raise BM25IndexError("Metadata missing corpus_hash")

    # Verify corpus_hash against current keywords (rebuild detection)
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
    _CACHED_INDEX = data
    _CACHED_PATH = path
    logger.info(
        "BM25 index loaded",
        extra={
            "path": str(path),
            "version": metadata.get("version"),
            "corpus_size": len(data["corpus"]),
        },
    )
    return cast(Dict[str, Any], data)


def get_scores(query: str) -> Dict[int, float]:
    """Get normalized BM25 relevance scores for all exemplars for a query.

    Scores are min-max normalized to [0, 1]. If all raw scores are equal
    (min == max), returns 0.0 for every exemplar. If the BM25 index is empty
    (no corpus), returns an empty dict.

    Args:
        query: Raw query string; tokenized using configured tokenizer.

    Returns:
        Mapping of exemplar_id → normalized_score in [0, 1].

    Raises:
        BM25IndexError: If index not loaded or scoring fails (except empty).
    """
    data = load_bm25()
    if data is None:
        raise BM25IndexError("BM25 index not loaded")
    bm25 = data["bm25_object"]
    entity_map = data["entity_map"]

    if bm25 is None:
        logger.debug("BM25 index is empty; no scores to return")
        return {}

    tokenized_query = _TOKENIZER(query)
    raw_scores = bm25.get_scores(tokenized_query)  # np.ndarray shape (N,)

    # Normalize to [0, 1]
    min_score = raw_scores.min()
    max_score = raw_scores.max()
    if max_score == min_score:
        normalized = np.zeros_like(raw_scores)
    else:
        normalized = (raw_scores - min_score) / (max_score - min_score)

    # Map corpus index -> exemplar_id
    inverse_map = {idx: eid for eid, idx in entity_map.items()}
    result: Dict[int, float] = {}
    for idx, score in enumerate(normalized):
        exemplar_id = inverse_map.get(idx)
        if exemplar_id is not None:
            result[exemplar_id] = float(score)

    return result


def get_top_n(query: str, n: int = 50) -> List[tuple[int, float]]:
    """Get top-N exemplars by BM25 score for the given query.

    Args:
        query: Raw query string.
        n: Number of top results to return (default 50).

    Returns:
        List of (exemplar_id, score) tuples sorted descending by score.

    Raises:
        BM25IndexError: If index not loaded or scoring fails.
    """
    scores = get_scores(query)
    sorted_items = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return sorted_items[:n]


# ── Utilities ────────────────────────────────────────────────────────────────


def get_index_info() -> Dict[str, object]:
    """Return metadata and basic stats about the loaded index.

    Returns:
        Dict with keys: version, created_at, corpus_hash, tokenizer_config,
        corpus_size, exemplar_count.
    """
    data = load_bm25()
    if data is None:
        raise BM25IndexError("BM25 index not loaded")
    meta = data["metadata"]
    return {
        "version": meta.get("version"),
        "created_at": meta.get("created_at"),
        "corpus_hash": meta.get("corpus_hash"),
        "tokenizer_config": meta.get("tokenizer_config"),
        "corpus_size": len(data["corpus"]),
        "exemplar_count": len(data["entity_map"]),
    }


def clear_cache() -> None:
    """Clear in-memory BM25 index cache (for testing)."""
    global _CACHED_INDEX, _CACHED_PATH
    _CACHED_INDEX = None
    _CACHED_PATH = None
    logger.debug("BM25 index cache cleared")
