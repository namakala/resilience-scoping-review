"""BM25 index exceptions."""


class BM25IndexError(Exception):
    """Base exception for all BM25 index errors."""

    pass


class IndexCorruptedError(BM25IndexError):
    """Raised when stored index corpus_hash differs from current keywords."""

    pass
