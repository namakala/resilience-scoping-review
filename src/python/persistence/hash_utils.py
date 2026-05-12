"""Hash computation utilities for embedding cache content-hash invalidation.

Provides deterministic fingerprinting for embedding model versions to support
cache validation and content-based invalidation.
"""

import hashlib

from utils.logging import get_logger

logger = get_logger(__name__)


def compute_model_hash(model_name: str) -> str:
    """Compute fingerprint for an embedding model version.

    Uses SHA256(model_name.encode()).hexdigest()[:16] to produce a 16-character
    identifier. Consistent with ADR-005 and implementation notes.

    Args:
        model_name: Name/identifier of the embedding model (e.g., "all-MiniLM-L6-v2").

    Returns:
        16-character hexadecimal model hash.
    """
    return hashlib.sha256(model_name.encode()).hexdigest()[:16]
