"""DAG constructor — ``create_pipeline(config) → hamilton.driver.Driver``.

Every node function is auto-discovered from the ``nodes`` package.  Hamilton
resolves dependencies by matching function parameter names to upstream function
names and config keys.
"""

from __future__ import annotations

from hamilton.driver import Builder
from pipeline.config import Config
from pipeline.nodes import (
    artifact_nodes,
    embedding_nodes,
    export_nodes,
    index_nodes,
    inference_nodes,
    retrieval_nodes,
    review_nodes,
)


def create_pipeline(
    config: Config,
    adapters: list[object] | None = None,
) -> Builder:
    """Construct a Hamilton DAG from all node functions.

    Parameters
    ----------
    config :
        Frozen snapshot of all application settings.  Injected into every node
        via Hamilton's ``with_config()`` so each function receives a typed
        ``config: Config`` parameter.
    adapters :
        Optional list of Hamilton lifecycle adapters (e.g.
        :class:`~pipeline.cache_adapter.NodeCacheAdapter`).  These are
        appended to the Builder's adapter chain.

    Returns
    -------
    Builder
        A Hamilton ``Builder`` ready for optional adapter/cache chaining.
        Call ``.build()`` to obtain a ``Driver``.
    """
    builder = (
        Builder()
        .with_modules(
            artifact_nodes,
            embedding_nodes,
            export_nodes,
            index_nodes,
            inference_nodes,
            retrieval_nodes,
            review_nodes,
        )
        .with_config({"config": config})
    )
    if adapters:
        for a in adapters:
            builder.adapters.append(a)
    return builder
