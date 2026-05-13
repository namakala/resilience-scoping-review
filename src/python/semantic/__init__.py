"""Semantic retrieval: BM25 indexing, embeddings, hybrid search."""

from .api import get_index_info, get_scores, get_top_n
from .cache import clear_cache as clear_bm25_cache
from .embedding_generation import generate_exemplar_embeddings
from .index_builder import build_index
from .keyword_embedding import generate_keyword_embeddings
from .keyword_extraction import extract_keywords
from .persistence import load_bm25, save_bm25
from .retrieval import hybrid_retrieve
from .similarity import compute_similarity

__all__ = [
    # BM25 index management
    "build_index",
    "save_bm25",
    "load_bm25",
    "get_scores",
    "get_top_n",
    "get_index_info",
    "clear_bm25_cache",
    # Embedding model
    "generate_embedding",
    "generate_embeddings",
    "get_model_hash",
    "clear_model_cache",
    "reload_model",
    "EmbeddingError",
    "MODEL_NAME",
    "EMBEDDING_DIM",
    "MODEL_CACHE_DIR",
    # Embedding generation
    "generate_exemplar_embeddings",
    "generate_keyword_embeddings",
    # Hybrid retrieval
    "hybrid_retrieve",
    # Similarity computation
    "compute_similarity",
    # Keyword extraction
    "extract_keywords",
    # Exceptions
    "BM25IndexError",
    "IndexCorruptedError",
    "CacheMissError",
]
