"""Rule implementations for ADR-013 constraint validation.

This module is internal to the ``ontology`` package.  It is not re-exported
from ``ontology.__init__``.  Import directly for unit testing::

    from ontology.rules import validate_code_approval

.. warning::
    This is **not** part of the public API.  Function signatures may
    change without notice across minor versions.
"""

from typing import Set

import networkx as nx

from .constraints import (
    CONSTRAINT_CODE_MULTI_THEME,
    CONSTRAINT_CYCLE_AFTER_MERGE,
    CONSTRAINT_MIN_CODES,
    CONSTRAINT_NONCONTIGUOUS_SPAN,
    CONSTRAINT_THEME_MULTI_INTERP,
    CONSTRAINT_UNKNOWN_TAG,
    ConstraintError,
)
from .contiguity import _missing_intermediates, is_contiguous_subtree

__all__ = [
    "validate_code_approval",
    "validate_theme_approval",
    "validate_theme_interpretation",
    "validate_interpretation_contiguity",
    "validate_tag_exists",
    "validate_no_cycle",
]


def validate_code_approval(
    code_id: int,
    graph: nx.DiGraph,
) -> None:
    """Rule 1: code belongs to at most one approved theme."""
    for src, tgt, data in graph.edges(data=True):
        if data.get("type") != "composed-of":
            continue
        if tgt != code_id:
            continue
        theme_status = graph.nodes[src].get("status", "")
        if theme_status == "approved":
            theme_name = graph.nodes[src].get("name", str(src))
            raise ConstraintError(
                CONSTRAINT_CODE_MULTI_THEME,
                f"Code '{code_id}' already belongs to approved theme "
                f"'{theme_name}'. A code can belong to at most one theme.",
            )


def validate_theme_approval(
    theme_id: int,
    graph: nx.DiGraph,
) -> None:
    """Rule 2: theme has >= 2 codes (themes may span multiple tags)."""
    code_ids: list[int] = []
    for src, tgt, data in graph.edges(data=True):
        if data.get("type") != "composed-of":
            continue
        if src != theme_id:
            continue
        code_ids.append(tgt)

    if len(code_ids) < 2:
        theme_name = graph.nodes[theme_id].get("name", str(theme_id))
        raise ConstraintError(
            CONSTRAINT_MIN_CODES,
            f"Theme '{theme_name}' has {len(code_ids)} code(s); "
            f"at least 2 are required.",
        )


def validate_theme_interpretation(
    theme_id: int,
    graph: nx.DiGraph,
) -> None:
    """Rule 3: theme belongs to at most one approved interpretation."""
    for src, tgt, data in graph.edges(data=True):
        if data.get("type") != "spans":
            continue
        if tgt != theme_id:
            continue
        interp_status = graph.nodes[src].get("status", "")
        if interp_status == "approved":
            interp_name = graph.nodes[src].get("name", str(src))
            raise ConstraintError(
                CONSTRAINT_THEME_MULTI_INTERP,
                f"Theme '{theme_id}' is already spanned by approved "
                f"interpretation '{interp_name}'. A theme can belong to "
                f"at most one interpretation.",
            )


def validate_interpretation_contiguity(
    tag_spans: Set[str],
    tag_dag: nx.DiGraph,
) -> None:
    """Rule 4: interpretation tag_spans form a contiguous subtree."""
    if not is_contiguous_subtree(tag_spans, tag_dag):
        missing = _missing_intermediates(tag_spans, tag_dag)
        hint = ""
        if missing:
            hint = (
                f" Missing intermediate tag(s): {sorted(missing)}. "
                f"Include them in tag_spans to make the span contiguous."
            )
        raise ConstraintError(
            CONSTRAINT_NONCONTIGUOUS_SPAN,
            f"Tags {sorted(tag_spans)} do not form a contiguous " f"subtree.{hint}",
        )


def validate_tag_exists(tag: str, tag_dag: nx.DiGraph) -> None:
    """Rule 5: tag must exist in the ontology DAG."""
    if tag not in tag_dag:
        raise ConstraintError(
            CONSTRAINT_UNKNOWN_TAG,
            f"Tag '{tag}' does not exist in the ontology. "
            f"Assign a valid tag from the ontology before proceeding.",
        )


def validate_no_cycle(graph: nx.DiGraph) -> None:
    """Rule 6: graph must be acyclic (pre-merge invariant check)."""
    try:
        cycle = nx.find_cycle(graph)
    except nx.NetworkXNoCycle:
        return

    cycle_str = " -> ".join(str(u) for u, _ in cycle[:5])
    raise ConstraintError(
        CONSTRAINT_CYCLE_AFTER_MERGE,
        f"Graph contains a cycle ({cycle_str}...). "
        f"Merging would corrupt data integrity. Investigate before "
        f"retrying.",
    )
