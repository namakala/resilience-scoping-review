"""Hybrid retrieval: scope -> BM25 -> embeddings -> rerank."""

from .api import hybrid_retrieve

__all__ = ["hybrid_retrieve"]
