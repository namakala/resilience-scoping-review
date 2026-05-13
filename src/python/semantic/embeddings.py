"""Sentence-transformer embedding model — lazy-loaded singleton with thread safety.

Model: all-MiniLM-L6-v2, 384-dim, CPU-only. Exposes generate_embedding() for
single-text encoding (L2-normalized via model) and cache management functions for
model lifecycle control.
"""

import os
import shutil
import threading
from pathlib import Path

import numpy as np
from persistence.hash_utils import compute_model_hash
from utils.logging import get_logger

logger = get_logger(__name__)

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "huggingface" / "hub"
MODEL_CACHE_DIR = Path(os.getenv("MODEL_CACHE_DIR", str(_DEFAULT_CACHE_DIR)))

_model = None
_model_hash: str | None = None
_lock = threading.Lock()


class EmbeddingError(Exception):
    """Raised when embedding generation fails."""


def _get_model_cache_subdir() -> Path:
    """Resolve the HF hub cache subdirectory for this model."""
    model_id = MODEL_NAME.replace("/", "--")
    return MODEL_CACHE_DIR / f"models--{model_id}"


def _get_model():
    """Lazy-load sentence-transformer model once (thread-safe).

    Uses double-checked locking. Imports SentenceTransformer inside function
    body to keep module import fast and allow clean mocking in tests.
    """
    global _model, _model_hash
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        from sentence_transformers import SentenceTransformer

        logger.info(
            "Loading embedding model",
            extra={
                "model": MODEL_NAME,
                "device": "cpu",
                "cache_dir": str(MODEL_CACHE_DIR),
            },
        )
        _model = SentenceTransformer(
            MODEL_NAME,
            device="cpu",
            cache_folder=str(MODEL_CACHE_DIR),
        )
        _model_hash = compute_model_hash(MODEL_NAME)
        logger.info(
            "Embedding model loaded",
            extra={
                "model": MODEL_NAME,
                "device": "cpu",
                "model_hash": _model_hash,
                "dim": EMBEDDING_DIM,
            },
        )
    return _model


def generate_embedding(text: str) -> np.ndarray:
    """Generate L2-normalized embedding vector for text.

    Args:
        text: Input text to embed.

    Returns:
        Float32 numpy array of shape (EMBEDDING_DIM,) normalized to unit L2.

    Raises:
        EmbeddingError: If model inference fails.
    """
    model = _get_model()
    with _lock:
        try:
            emb = model.encode(text, normalize_embeddings=True)
        except Exception as e:
            logger.error("Embedding generation failed", extra={"error": str(e)})
            raise EmbeddingError(f"Failed to generate embedding: {e}") from e
    return emb


def generate_embeddings(texts: list[str], batch_size: int = 32) -> np.ndarray:
    """Generate L2-normalized embeddings for a batch of texts.

    More efficient than calling generate_embedding() in a loop because
    the model processes texts in internal batches.

    Args:
        texts: List of input texts to embed.
        batch_size: Internal encode batch size passed to the model.

    Returns:
        Float32 numpy array of shape (len(texts), EMBEDDING_DIM)
        with each row L2-normalized to unit length.

    Raises:
        EmbeddingError: If model inference fails.
    """
    model = _get_model()
    with _lock:
        try:
            embs = model.encode(texts, normalize_embeddings=True, batch_size=batch_size)
        except Exception as e:
            logger.error("Batch embedding generation failed", extra={"error": str(e)})
            raise EmbeddingError(f"Failed to generate embeddings: {e}") from e
    return embs


def get_model_hash() -> str:
    """Return model version hash for cache invalidation.

    Triggers model load if not already loaded.

    Returns:
        16-character hexadecimal model hash.
    """
    if _model_hash is None:
        _get_model()
    assert _model_hash is not None
    return _model_hash


def clear_model_cache() -> None:
    """Remove cached model files from disk and reset in-memory singleton.

    The model subdirectory within MODEL_CACHE_DIR is deleted. The singleton
    is reset so the next generate_embedding() call will re-download.
    """
    global _model, _model_hash
    _model = None
    _model_hash = None
    cache_dir = _get_model_cache_subdir()
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
        logger.info("Model cache cleared", extra={"path": str(cache_dir)})
    else:
        logger.debug("No model cache to clear", extra={"path": str(cache_dir)})


def reload_model(clear_cache: bool = False) -> None:
    """Reset the model singleton; optionally clear disk cache.

    Args:
        clear_cache: If True, also removes cached model files from disk.
            The model will be re-downloaded on the next generate_embedding()
            call.
    """
    if clear_cache:
        clear_model_cache()
    else:
        global _model, _model_hash
        _model = None
        _model_hash = None
        logger.info("Model state reset; will reload on next generate_embedding call")
