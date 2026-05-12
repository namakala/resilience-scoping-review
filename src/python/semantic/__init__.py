"""Semantic retrieval layer: BM25 lexical indexing, embeddings, hybrid search."""

from .bm25_index import BM25IndexError, IndexCorruptedError, build_index
from .bm25_index import clear_cache as clear_bm25_cache
from .bm25_index import get_index_info, get_scores, get_top_n, load_bm25, save_bm25

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
