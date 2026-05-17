"""Convert ``InterpretationInference`` results into graph interpretation nodes.

Creates interpretation nodes (type='interpretation', status='draft') with
``tag_spans`` in ``data_json``, ``spans`` edges to constituent themes,
and ``derived-from`` edges on re-synthesis.

Non-contiguous tag_spans are handled via a pool-based reprocessing flow:

1. **Separate** — contiguous interpretations + largest component (non-WCC)
   are created immediately.  Smaller components (WCC) go to a pool.
2. **Batch 1** — create nodes for all contiguous + non-WCC items.
3. **Process pool** — group WCC themes by tag contiguity; leftover themes
   use hybrid semantic similarity (name + narrative + exemplar embeddings)
   for clustering.
4. **Batch 2** — create nodes for all resulting pool items.

Usage:
    from inference.interpretation_creation import create_interpretation_nodes
    node_ids = create_interpretation_nodes(con, synthesize_interpretations(con))
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import duckdb
import networkx as nx
import numpy as np
from graph import (
    create_edge,
    create_node,
    get_node,
    get_nodes_by_type_and_tag,
    graph_transaction,
)
from ontology import (
    invalidate_cache_for_tags,
    is_contiguous_subtree,
    partition_into_contiguous_components,
)
from ontology.dag import get_tag_dag
from semantic.similarity import compute_theme_hybrid_similarity
from utils.logging import get_logger

from .inference_status_crud import set_status
from .inference_status_types import (
    ENTITY_INTERPRETATION,
    GENERATED,
    STAGE_INTERPRETATION,
)
from .interpretation_node_reinfer import rename_node_raw
from .interpretation_tag_utils import compute_tag_spans
from .name_utils import check_duplicate_names, make_unique_name
from .parsing import InterpretationInference

logger = get_logger(__name__)

__all__ = ["create_interpretation_nodes"]


# ── Internal types ─────────────────────────────────────────────────────────


@dataclass
class _PoolItem:
    """A theme group extracted from a non-contiguous interpretation.

    Represents one WCC component that was smaller than the largest
    component within its originating interpretation.
    """

    name: str
    narrative: str
    key_insights: list[str]
    theme_ids: list[str]
    theme_tags: set[str] = field(default_factory=set)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _resolve_theme_tag(theme_id_str: str, db_path: Optional[Path] = None) -> str:
    """Resolve a theme ID string to its ontology tag."""
    clean_id = "".join(c for c in theme_id_str if c.isdigit())
    if not clean_id:
        return ""
    try:
        theme = get_node(int(clean_id), db_path=db_path)
        tag: str = theme.get("tag", "")
        return tag
    except (KeyError, ValueError):
        return ""


def _make_interp_from_pool_item(
    item: _PoolItem,
    suffix: str = "",
) -> InterpretationInference:
    """Convert a ``_PoolItem`` back to an ``InterpretationInference``."""
    return InterpretationInference(
        interpretation_name=item.name + suffix,
        narrative=item.narrative,
        theme_ids=item.theme_ids,
        key_insights=item.key_insights,
        tag="",
    )


def _build_data_json(tag_spans: set[str]) -> dict:
    """Build the ``data_json`` payload for an interpretation node."""
    return {"tag_spans": sorted(tag_spans)}


def _load_all_interpretation_names(
    db_path: Optional[Path] = None,
) -> set[str]:
    """Fetch ALL existing interpretation node names across all tags."""
    nodes = get_nodes_by_type_and_tag("interpretation", None, db_path=db_path)
    return {n["name"] for n in nodes}


def _theme_ids_by_tag(
    theme_ids: list[str], db_path: Optional[Path] = None
) -> dict[str, list[str]]:
    """Group theme IDs by their ontology tag.

    Returns ``{tag: [theme_id_str, ...]}``.
    """
    by_tag: dict[str, list[str]] = defaultdict(list)
    for tid in theme_ids:
        tag = _resolve_theme_tag(tid, db_path)
        if tag:
            by_tag[tag].append(tid)
    return by_tag


# ── Phase 1: Separate interpretations ──────────────────────────────────────


def _separate_by_contiguity(
    interpretations: list[InterpretationInference],
    db_path: Optional[Path] = None,
) -> tuple[list[InterpretationInference], list[_PoolItem]]:
    """Separate *interpretations* into batch-1 and WCC pool.

    Returns ``(batch1, pool)`` where:

    * **batch1** — interpretations that are already contiguous, plus
      the **largest** component(s) of non-contiguous interpretations
      (non-WCC).  All tied-largest components are included.

    * **pool** — themes from all **strictly smaller** components
      (WCC) across all non-contiguous interpretations.

    When all components are size 1, everything goes to *pool* and
    *batch1* receives nothing from that interpretation.
    """
    tag_span_map = compute_tag_spans(interpretations, db_path=db_path)
    batch1: list[InterpretationInference] = []
    pool: list[_PoolItem] = []

    for interp in interpretations:
        tag_spans, _ = tag_span_map[interp.interpretation_name]
        if len(tag_spans) <= 1 or is_contiguous_subtree(tag_spans):
            # Already contiguous — create immediately
            batch1.append(interp)
            continue

        # Non-contiguous — decompose into WCC components
        components = partition_into_contiguous_components(tag_spans)
        if not components:
            # Shouldn't happen, but safeguard
            batch1.append(interp)
            continue

        # Resolve theme_id → tag for this interpretation
        tid_by_tag = _theme_ids_by_tag(interp.theme_ids, db_path=db_path)

        # Build theme_ids for each component
        comp_items: list[tuple[set[str], list[str]]] = []
        for comp in components:
            comp_theme_ids = [
                tid for tag, tids in tid_by_tag.items() if tag in comp for tid in tids
            ]
            if comp_theme_ids:
                comp_items.append((comp, comp_theme_ids))

        if not comp_items:
            batch1.append(interp)
            continue

        # Sort by component size descending, then by number of themes
        comp_items.sort(key=lambda x: (len(x[0]), len(x[1])), reverse=True)

        max_size = len(comp_items[0][0])
        for i, (comp, comp_tids) in enumerate(comp_items):
            item = _PoolItem(
                name=interp.interpretation_name,
                narrative=interp.narrative,
                key_insights=interp.key_insights,
                theme_ids=comp_tids,
                theme_tags=comp,
            )
            # Largest component (= non-WCC) goes to batch1.
            # All strictly smaller components (= WCC) go to pool.
            # When all are same size (e.g. all size 1), everything goes to pool.
            if len(comp) == max_size and len(comp) >= 2 and i == 0:
                # Only the single largest multi-tag component is non-WCC
                batch1.append(_make_interp_from_pool_item(item))
            else:
                pool.append(item)

    return batch1, pool


# ── Phase 2 / 4: Create interpretation nodes in a transaction ──────────────


def _create_interpretation_batch(
    con: duckdb.DuckDBPyConnection,
    interpretations: list[InterpretationInference],
    existing_draft: dict[str, int],
    used_names: set[str],
    superseded_names: set[str],
    db_path: Optional[Path] = None,
) -> tuple[list[int], set[str]]:
    """Create interpretation nodes for a batch inside a single transaction.

    Returns ``(node_ids, all_span_tags)``.
    """
    if not interpretations:
        return [], set()

    tag_span_map = compute_tag_spans(interpretations, db_path=db_path)
    node_ids: list[int] = []
    all_span_tags: set[str] = set()

    with graph_transaction(db_path=db_path):
        # Rename superseded interpretations
        for interp in interpretations:
            if interp.interpretation_name in superseded_names:
                old_id = existing_draft[interp.interpretation_name]
                rename_node_raw(
                    old_id,
                    f"{interp.interpretation_name}_deprecated_{old_id}",
                    db_path=db_path,
                )

        for interp in interpretations:
            _, root_tag = tag_span_map[interp.interpretation_name]
            unique_name = make_unique_name(
                interp.interpretation_name,
                used_names,
                entity_type="interpretation",
            )

            # Cross-tag collision safety net
            other_tag_interp_names = set()
            for n in get_nodes_by_type_and_tag("interpretation", None, db_path=db_path):
                t = n.get("tag")
                if t != root_tag and n.get("status") in ("draft", "approved"):
                    other_tag_interp_names.add(n["name"])
            other_tag_interp_names -= superseded_names
            if unique_name in other_tag_interp_names:
                qualified = f"{unique_name} [span]"
                logger.warning(
                    "Cross-tag interpretation name collision '%s' resolved to '%s'",
                    unique_name,
                    qualified,
                )
                unique_name = make_unique_name(qualified, other_tag_interp_names)

            used_names.add(unique_name)

            tag_spans, root_tag = tag_span_map[interp.interpretation_name]
            all_span_tags.update(tag_spans)

            node_id = create_node(
                node_type="interpretation",
                name=unique_name,
                definition=interp.narrative,
                tag=root_tag,
                status="draft",
                data_json=_build_data_json(tag_spans),
                db_path=db_path,
            )
            node_ids.append(node_id)

            prev_id = existing_draft.get(interp.interpretation_name)
            if prev_id is not None:
                create_edge(
                    source_id=prev_id,
                    target_id=node_id,
                    edge_type="derived-from",
                    db_path=db_path,
                )

            for theme_id_str in interp.theme_ids:
                try:
                    clean_id = "".join(c for c in theme_id_str if c.isdigit())
                    if not clean_id:
                        raise ValueError(f"No digits in '{theme_id_str}'")
                    theme_id = int(clean_id)
                except (ValueError, TypeError):
                    logger.error(
                        "Invalid theme_id '%s' in interpretation '%s'; skipping edge",
                        theme_id_str,
                        interp.interpretation_name,
                    )
                    continue
                create_edge(
                    source_id=node_id,
                    target_id=theme_id,
                    edge_type="spans",
                    db_path=db_path,
                )

    return node_ids, all_span_tags


# ── Phase 3: Process WCC pool ──────────────────────────────────────────────


def _group_pool_by_contiguity(
    pool: list[_PoolItem],
) -> tuple[list[_PoolItem], list[_PoolItem]]:
    """Group WCC pool items by tag contiguity.

    Collects all tags across all pool items, finds WCCs of the induced
    subgraph, and merges items whose tags form a contiguous subtree.

    Returns ``(contiguous_groups, leftovers)``.

    * **contiguous_groups** — merged ``_PoolItem`` objects where
      multiple pool items were combined into one contiguous span.
    * **leftovers** — single-tag or non-contiguous items that could
      not be merged with any other.
    """
    if not pool:
        return [], []

    # Collect all tags from all pool items, mapped back to items
    tag_to_items: dict[str, list[_PoolItem]] = defaultdict(list)
    for item in pool:
        for tag in item.theme_tags:
            tag_to_items[tag].append(item)

    all_tags = set(tag_to_items.keys())
    if len(all_tags) <= 1:
        # Nothing to merge — everything is already a single tag
        return [], pool

    dag = get_tag_dag()
    induced = dag.subgraph(all_tags)
    components = list(nx.weakly_connected_components(induced))

    contiguous_groups: list[_PoolItem] = []
    leftovers: list[_PoolItem] = []
    assigned_items: set[int] = set()

    for comp in components:
        if len(comp) <= 1:
            # Single-tag component — cannot merge
            continue

        if not is_contiguous_subtree(comp):
            # Non-contiguous component — cannot merge
            continue

        # Find all pool items that have themes in this component
        merged_theme_ids: list[str] = []
        merged_tags: set[str] = set()
        merged_items: list[_PoolItem] = []

        for tag in comp:
            for item in tag_to_items.get(tag, []):
                idx = id(item)
                if idx not in assigned_items:
                    merged_items.append(item)
                    assigned_items.add(idx)
                    merged_theme_ids.extend(item.theme_ids)
                    merged_tags.update(item.theme_tags)

        if not merged_theme_ids:
            continue

        if len(merged_items) == 1:
            # Only one item in this component — no merge opportunity
            continue

        # Deduplicate theme_ids while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for tid in merged_theme_ids:
            if tid not in seen:
                seen.add(tid)
                deduped.append(tid)

        # Use the name of the item with the most themes
        best_item = max(merged_items, key=lambda it: len(it.theme_ids))

        group = _PoolItem(
            name=best_item.name,
            narrative=best_item.narrative,
            key_insights=best_item.key_insights,
            theme_ids=deduped,
            theme_tags=merged_tags,
        )
        contiguous_groups.append(group)

    # Remaining items → leftovers
    for i, item in enumerate(pool):
        if id(item) not in assigned_items:
            leftovers.append(item)

    return contiguous_groups, leftovers


def _cluster_leftover_themes(
    leftovers: list[_PoolItem],
    con: duckdb.DuckDBPyConnection,
    db_path: Optional[Path] = None,
) -> list[InterpretationInference]:
    """Cluster leftover pool themes using hybrid semantic similarity.

    For each pair of leftover items, computes
    :func:`~semantic.similarity.compute_theme_hybrid_similarity`.
    Uses threshold-based union-find clustering.

    Each resulting cluster becomes one ``InterpretationInference``.
    If a cluster's tag_spans is still non-contiguous, a warning is
    logged and the interpretation is created anyway (bypass).
    """
    if not leftovers:
        return []

    n = len(leftovers)
    sim_matrix = np.zeros((n, n), dtype="float32")

    for i in range(n):
        for j in range(i + 1, n):
            a, b = leftovers[i], leftovers[j]
            # Collect exemplar IDs for both items
            ex_ids_a = _collect_exemplar_ids(a.theme_ids, db_path)
            ex_ids_b = _collect_exemplar_ids(b.theme_ids, db_path)
            try:
                score = compute_theme_hybrid_similarity(
                    name_a=a.name,
                    narrative_a=a.narrative,
                    exemplar_ids_a=ex_ids_a,
                    name_b=b.name,
                    narrative_b=b.narrative,
                    exemplar_ids_b=ex_ids_b,
                    con=con,
                )
            except Exception:
                logger.warning(
                    "Hybrid similarity failed for '%s' <-> '%s'; using 0.0",
                    a.name,
                    b.name,
                )
                score = 0.0
            sim_matrix[i, j] = score
            sim_matrix[j, i] = score
    np.fill_diagonal(sim_matrix, 1.0)

    # Union-Find clustering
    parent = list(range(n))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(x: int, y: int) -> None:
        px, py = _find(x), _find(y)
        if px != py:
            parent[px] = py

    threshold = 0.5  # balanced threshold for hybrid theme similarity
    for i in range(n):
        for j in range(i + 1, n):
            if sim_matrix[i, j] >= threshold:
                _union(i, j)

    by_root: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        by_root[_find(i)].append(i)

    results: list[InterpretationInference] = []
    for group_indices in by_root.values():
        if not group_indices:
            continue
        merged_theme_ids: list[str] = []
        merged_tags: set[str] = set()
        name_counter: dict[str, int] = defaultdict(int)

        for idx in group_indices:
            item = leftovers[idx]
            merged_theme_ids.extend(item.theme_ids)
            merged_tags.update(item.theme_tags)
            name_counter[item.name] += 1

        # Deduplicate theme_ids
        seen: set[str] = set()
        deduped: list[str] = []
        for tid in merged_theme_ids:
            if tid not in seen:
                seen.add(tid)
                deduped.append(tid)

        # Name: most common name in the cluster
        best_name = max(name_counter, key=lambda k: name_counter[k])

        # Use the narrative and key_insights from the item with most themes
        best_item = max(
            (leftovers[idx] for idx in group_indices), key=lambda it: len(it.theme_ids)
        )

        interp = InterpretationInference(
            interpretation_name=best_name,
            narrative=best_item.narrative,
            theme_ids=deduped,
            key_insights=best_item.key_insights,
            tag="",
        )

        # Check contiguity — bypass if still non-contiguous
        if len(merged_tags) > 1 and not is_contiguous_subtree(merged_tags):
            logger.warning(
                "Semantic cluster '%s' still has non-contiguous tag_spans %s; "
                "bypassing contiguity validation and creating anyway",
                best_name,
                sorted(merged_tags),
            )

        results.append(interp)

    return results


def _collect_exemplar_ids(
    theme_ids: list[str],
    db_path: Optional[Path] = None,
) -> list[int]:
    """Collect all exemplar IDs referenced by a list of themes.

    Traverses theme → codes (via data_json['code_ids']) → exemplars
    (via each code node's data_json['exemplar_ids']).
    """
    all_ids: set[int] = set()
    for tid_str in theme_ids:
        clean_id = "".join(c for c in tid_str if c.isdigit())
        if not clean_id:
            continue
        try:
            theme = get_node(int(clean_id), db_path=db_path)
        except (KeyError, ValueError):
            continue
        code_ids = theme.get("data_json", {}).get("code_ids", [])
        for cid_str in code_ids:
            c_clean = "".join(c for c in str(cid_str) if c.isdigit())
            if not c_clean:
                continue
            try:
                code_node = get_node(int(c_clean), db_path=db_path)
            except (KeyError, ValueError):
                continue
            ex_ids = code_node.get("data_json", {}).get("exemplar_ids", [])
            for eid in ex_ids:
                try:
                    all_ids.add(int(eid))
                except (ValueError, TypeError):
                    continue
    return sorted(all_ids)


# ── Main entry point ───────────────────────────────────────────────────────


def create_interpretation_nodes(
    con: duckdb.DuckDBPyConnection,
    interpretations: list[InterpretationInference],
    db_path: Optional[Path] = None,
) -> list[int]:
    """Convert *interpretations* into graph nodes with ``spans`` edges.

    Handles non-contiguous tag_spans via a pool-based reprocessing flow:

    1. Interpretations with contiguous (or single-tag) tag_spans are
       created immediately.
    2. For non-contiguous interpretations, the largest component
       (non-WCC) is created immediately; smaller components (WCC) are
       pooled.
    3. The WCC pool is first grouped by tag contiguity, then remaining
       leftovers are clustered via hybrid semantic similarity.
    4. All pool results are created in a second batch.

    Args:
        con: Active DuckDB connection.
        interpretations: List of :class:`InterpretationInference` items.
        db_path: Optional DuckDB path for graph module.

    Returns:
        List of created interpretation node IDs.

    Raises:
        ValueError: If empty or missing name.
        KeyError: If a referenced theme ID does not exist.
    """
    # ── Input validation ───────────────────────────────────────────────
    if not interpretations:
        logger.warning("create_interpretation_nodes called with empty list; no-op")
        return []

    for interp in interpretations:
        if not interp.interpretation_name:
            raise ValueError(
                f"InterpretationInference has empty interpretation_name: {interp}"
            )
        if not interp.theme_ids:
            logger.warning(
                "Interpretation '%s' has no theme_ids; creating node anyway",
                interp.interpretation_name,
            )

    check_duplicate_names(
        interpretations,
        lambda i: i.interpretation_name,
        entity_type="interpretation",
    )

    # ── Phase 1: Separate by contiguity ─────────────────────────────────
    batch1, pool = _separate_by_contiguity(interpretations, db_path=db_path)

    logger.info(
        "Phase 1 separation: %d contiguous/non-WCC + %d WCC pool item(s)",
        len(batch1),
        len(pool),
    )

    # ── Pre-transaction: detect re-synthesis candidates ─────────────────
    from graph.queries import load_occupied_names
    from persistence.state_constants import NON_APPROVED_STATUSES

    existing_names = load_occupied_names(
        "interpretation", statuses=NON_APPROVED_STATUSES, db_path=db_path
    )
    superseded_names: set[str] = {
        i.interpretation_name for i in batch1 if i.interpretation_name in existing_names
    }
    used_names: set[str] = {n for n in existing_names if n not in superseded_names}

    all_node_ids: list[int] = []
    all_span_tags: set[str] = set()

    # ── Phase 2: Create batch 1 (contiguous + non-WCC) ─────────────────
    if batch1:
        logger.info(
            "Batch 1: creating %d interpretation node(s)",
            len(batch1),
        )
        b1_ids, b1_tags = _create_interpretation_batch(
            con,
            batch1,
            existing_names,
            used_names,
            superseded_names,
            db_path=db_path,
        )
        all_node_ids.extend(b1_ids)
        all_span_tags.update(b1_tags)

    # ── Phase 3: Process WCC pool ───────────────────────────────────────
    if pool:
        logger.info("Processing WCC pool: %d item(s)", len(pool))

        # Step A: Group by tag contiguity
        contig_groups, leftovers = _group_pool_by_contiguity(pool)

        if contig_groups:
            logger.info("Pool contiguity grouping: %d group(s)", len(contig_groups))

        # Step B: Semantic similarity for leftovers
        pool_interps: list[InterpretationInference] = []

        for group in contig_groups:
            pool_interps.append(_make_interp_from_pool_item(group, suffix=""))

        if leftovers:
            logger.info(
                "Pool leftovers: %d item(s) → semantic clustering", len(leftovers)
            )
            clustered = _cluster_leftover_themes(leftovers, con, db_path=db_path)
            pool_interps.extend(clustered)

        # Deduplicate pool interpretation names
        if pool_interps:
            check_duplicate_names(
                pool_interps,
                lambda i: i.interpretation_name,
                entity_type="interpretation",
            )

            # ── Phase 4: Create pool nodes ─────────────────────────
            logger.info(
                "Batch 2: creating %d pool interpretation node(s)", len(pool_interps)
            )
            b2_ids, b2_tags = _create_interpretation_batch(
                con,
                pool_interps,
                existing_draft={},  # pool items don't re-synthesize
                used_names=used_names,
                superseded_names=set(),
                db_path=db_path,
            )
            all_node_ids.extend(b2_ids)
            all_span_tags.update(b2_tags)

    # ── Post-transaction: update inference_status ──────────────────────
    for node_id in all_node_ids:
        set_status(
            con,
            entity_id=str(node_id),
            entity_type=ENTITY_INTERPRETATION,
            stage=STAGE_INTERPRETATION,
            status=GENERATED,
        )

    # ── Post-transaction: invalidate caches ────────────────────────────
    if all_span_tags:
        try:
            invalidate_cache_for_tags(
                list(all_span_tags), db_path=db_path, reason="interpretation-creation"
            )
        except Exception:
            logger.warning(
                "Cache invalidation failed for tags %s; continuing",
                sorted(all_span_tags),
            )

    logger.info(
        "Created %d interpretation nodes spanning tags %s",
        len(all_node_ids),
        sorted(all_span_tags),
    )
    return all_node_ids
