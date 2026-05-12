"""Semantic retrieval layer: BM25 lexical indexing, embeddings, hybrid search."""

from .api import get_index_info, get_scores, get_top_n
from .cache import clear_cache as clear_bm25_cache
from .exceptions import BM25IndexError, IndexCorruptedError
from .index_builder import build_index
from .persistence import load_bm25, save_bm25

__all__ = [
    # BM25 index management
    "build_index",
    "save_bm25",
    "load_bm25",
    "get_scores",
    "get_top_n",
    "get_index_info",
    "clear_bm25_cache",
    # Exceptions
    "BM25IndexError",
    "IndexCorruptedError",
]
