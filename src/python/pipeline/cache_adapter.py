"""Hamilton lifecycle adapter for per-node result caching.

Intercepts ``do_node_execute`` to check the DuckDB ``node_cache`` before
computing.  Cache hits return the stored result directly; cache misses
compute, store, and return.

Exposes ``CacheMetrics`` for the executor to read hit/miss counts after
a DAG run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import duckdb
from persistence.node_cache import load_cached, store_cached
from pipeline.caching import compute_inputs_hash
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CacheMetrics:
    """Mutable counters shared between the adapter and the executor.

    The adapter updates these during ``do_node_execute``; the executor
    reads them after ``driver.execute()`` to populate ``ExecutionResult``
    and per-node ``"cached"`` records.
    """

    hit_count: int = 0
    miss_count: int = 0
    cached_nodes: set[str] = field(default_factory=set)


# ── Nodes whose results are expensive enough to cache ────────────────
# Nodes not in this set are executed normally (cache bypass).
_CACHEABLE_NODES: frozenset[str] = frozenset(
    {
        # Embedding (Stage 2)
        "embed_exemplars",
        "embed_keywords",
        "embed_codes",
        "embed_themes",
        "cache_exemplar_embeddings",
        "cache_keyword_embeddings",
        # Index (Stage 3)
        "build_bm25",
        "build_ontology_graph",
        "materialize_traversal_cache",
        # Retrieval (Stage 4, 6, 8)
        "retrieve_code_candidates",
        "retrieve_theme_candidates",
        "retrieve_interpretation_candidates",
        # Inference (Stage 4, 6, 8) — expensive LLM calls
        "infer_codes",
        "infer_themes",
        "infer_interpretations",
    }
)


class NodeCacheAdapter:
    """Hamilton lifecycle adapter.

    Usage::

        metrics = CacheMetrics()
        con = get_connection()
        adapter = NodeCacheAdapter(con, metrics)
        builder.adapters.append(adapter)
        driver = builder.build()
        result = execute_dag(driver, ..., cache_metrics=metrics)
    """

    def __init__(
        self,
        con: duckdb.DuckDBPyConnection,
        metrics: CacheMetrics,
    ) -> None:
        self._con = con
        self._metrics = metrics

    # ── Lifecycle: per-node execution ────────────────────────────────

    def do_node_execute(
        self,
        *,
        run_id: str,
        node_: Any,
        kwargs: dict[str, Any],
        task_id: str | None = None,
        **future_kwargs: Any,
    ) -> Any:
        """Check ``node_cache`` before executing *node_*.

        If a cached result exists for ``(node_.name, inputs_hash)``, return
        it without calling ``node_.callable``.  Otherwise compute, store,
        and return.
        """
        node_id = node_.name

        # Only cache declared nodes
        if node_id not in _CACHEABLE_NODES:
            return node_.callable(**kwargs)

        # Compute deterministic hash of the resolved inputs
        inputs_hash = compute_inputs_hash(kwargs)
        if inputs_hash is None:
            # Normalization failed — fall through to normal execution
            return node_.callable(**kwargs)

        # ── cache check ─────────────────────────────────────────────
        cached = load_cached(self._con, node_id, inputs_hash)
        if cached is not None:
            self._metrics.hit_count += 1
            self._metrics.cached_nodes.add(node_id)
            logger.info(
                "cache hit for node",
                extra={"node": node_id, "inputs_hash": inputs_hash},
            )
            return cached

        # ── cache miss → compute ────────────────────────────────────
        self._metrics.miss_count += 1
        logger.info(
            "cache miss: computing",
            extra={"node": node_id, "inputs_hash": inputs_hash},
        )
        result = node_.callable(**kwargs)

        store_cached(self._con, node_id, inputs_hash, result)
        return result
