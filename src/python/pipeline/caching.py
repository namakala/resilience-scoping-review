"""Input normalization and deterministic hashing for node result caching.

``compute_inputs_hash(inputs_dict)`` produces a stable SHA-256 hex digest
from a node's keyword arguments, suitable for use as a ``node_cache`` key.

Type normalizers convert non-JSON types (Polars, NetworkX, NumPy, dataclasses,
etc.) to JSON-safe dicts before hashing.  Unhandled types fall back to
``repr()`` with a warning.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any

import networkx as nx
import numpy as np
import polars as pl
from utils.logging import get_logger

logger = get_logger(__name__)


def _normalize_value(v: Any) -> Any:
    """Recursively convert *v* to a JSON-safe, deterministic representation.

    Handles:
    - Primitives (None, bool, int, float, str) → passed through
    - ``list`` / ``tuple`` → recursively normalized
    - ``dict`` → keys sorted, values recursively normalized
    - ``pl.LazyFrame`` → schema dict (columns + dtypes)
    - ``nx.DiGraph`` → ``nx.node_link_data()``
    - ``np.ndarray`` → ``tolist()``
    - dataclasses → ``dataclasses.asdict()`` then normalized
    - Fallback → ``{"__repr": repr(v)[:200]}`` with debug log
    """
    if v is None or isinstance(v, (bool, int, float, str)):
        return v

    if isinstance(v, (list, tuple)):
        return [_normalize_value(x) for x in v]

    if isinstance(v, dict):
        return {str(k): _normalize_value(v) for k, v in sorted(v.items())}

    if isinstance(v, pl.LazyFrame):
        try:
            schema = v.collect_schema()
            return {
                "__type": "LazyFrame",
                "columns": list(schema.names()),
                "dtypes": [str(t) for t in schema.dtypes()],
            }
        except Exception as exc:
            logger.debug(
                "Could not read LazyFrame schema for hashing",
                extra={"error": str(exc)},
            )
            return {"__type": "LazyFrame", "__repr": repr(v)[:200]}

    if isinstance(v, pl.DataFrame):
        try:
            schema = v.schema
            return {
                "__type": "DataFrame",
                "columns": list(schema.names()),
                "dtypes": [str(t) for t in schema.dtypes()],
                "height": v.height,
            }
        except Exception as exc:
            logger.debug(
                "Could not read DataFrame schema for hashing",
                extra={"error": str(exc)},
            )
            return {"__type": "DataFrame", "__repr": repr(v)[:200]}

    if isinstance(v, nx.DiGraph):
        try:
            return {"__type": "DiGraph", "data": nx.node_link_data(v)}
        except Exception as exc:
            logger.debug(
                "Could not serialize DiGraph for hashing",
                extra={"error": str(exc)},
            )
            return {"__type": "DiGraph", "__repr": repr(v)[:200]}

    if isinstance(v, np.ndarray):
        return {
            "__type": "ndarray",
            "shape": list(v.shape),
            "dtype": str(v.dtype),
            "data": v.tolist(),
        }

    if dataclasses and dataclasses.is_dataclass(v):
        try:
            return _normalize_value(dataclasses.asdict(v))
        except Exception as exc:
            logger.debug(
                "Could not serialize dataclass for hashing",
                extra={"type": type(v).__name__, "error": str(exc)},
            )
            return {"__type": type(v).__name__, "__repr": repr(v)[:200]}

    # Fallback: repr truncated
    logger.debug(
        "Unhandled type for inputs hash — using repr fallback",
        extra={"type": type(v).__name__},
    )
    return {"__type": type(v).__name__, "__repr": repr(v)[:200]}


def compute_inputs_hash(inputs: dict[str, Any]) -> str | None:
    """Compute a deterministic SHA-256 hex digest for a node's inputs dict.

    Uses ``json.dumps`` with sorted keys and custom type normalizers.
    Returns ``None`` if any input value fails normalisation (should not
    happen under normal circumstances; the fallback stores ``repr``).

    Args:
        inputs: The keyword-argument dict that will be passed to a node
            function.  Typically retrieved from a Hamilton lifecycle hook.

    Returns:
        64-character SHA-256 hex string, or ``None`` on failure.
    """
    try:
        normalized = _normalize_value(dict(inputs))
        # _normalize_value on a dict returns {str(k): ...}
        if not isinstance(normalized, dict):
            logger.warning(
                "Input normalization did not produce a dict",
                extra={"type": type(normalized).__name__},
            )
            return None
        canonical = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    except Exception as exc:
        logger.error(
            "Failed to compute inputs hash",
            extra={"error": str(exc)},
        )
        return None
