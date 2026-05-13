"""Semantic-layer exceptions.

Includes BM25 index errors and embedding cache errors.
"""


class BM25IndexError(Exception):
    """Base exception for all BM25 index errors."""

    pass


class IndexCorruptedError(BM25IndexError):
    """Raised when stored index corpus_hash differs from current keywords."""

    pass


class CacheMissError(Exception):
    """Raised when a required embedding is not found in the cache."""

    pass
