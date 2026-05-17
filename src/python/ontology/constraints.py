"""Constraint validator: ADR-013 dispatch.

Public API exported via ``ontology.__init__``:

* ``ConstraintError`` — raised on violation
* ``validate_constraint(entity, action)`` — main dispatch
* ``is_contiguous_subtree(tags)`` — shared with Feature 50

Implementation detail modules (not re-exported):

* ``rules`` — 6 rule functions (testable, ``__all__``-controlled)
* ``contiguity`` — contiguous-subtree check (standalone)
"""

from typing import Any, Optional

import networkx as nx

# ---------------------------------------------------------------------------
# Error codes + exception  (must be defined before importing rules)
# ---------------------------------------------------------------------------
CONSTRAINT_CODE_MULTI_THEME = "CONSTRAINT_CODE_MULTI_THEME"
CONSTRAINT_MIN_CODES = "CONSTRAINT_MIN_CODES"
CONSTRAINT_TAG_MISMATCH = "CONSTRAINT_TAG_MISMATCH"
CONSTRAINT_THEME_MULTI_INTERP = "CONSTRAINT_THEME_MULTI_INTERP"
CONSTRAINT_NONCONTIGUOUS_SPAN = "CONSTRAINT_NONCONTIGUOUS_SPAN"
CONSTRAINT_UNKNOWN_TAG = "CONSTRAINT_UNKNOWN_TAG"
CONSTRAINT_CYCLE_AFTER_MERGE = "CONSTRAINT_CYCLE_AFTER_MERGE"


class ConstraintError(ValueError):
    """Raised when a constraint validation fails.

    Attributes:
        code: Machine-readable error code string.
        message: Human-readable description with details and hint.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


# ---------------------------------------------------------------------------
# Import rule implementations (ConstraintError must be defined first)
# ---------------------------------------------------------------------------
from .contiguity import (  # noqa: E402, F401
    is_contiguous_subtree,
    partition_into_contiguous_components,
)
from .rules import (  # noqa: E402
    validate_code_approval,
    validate_interpretation_contiguity,
    validate_no_cycle,
    validate_tag_exists,
    validate_theme_approval,
    validate_theme_interpretation,
)

# ---------------------------------------------------------------------------
# Graph / DAG resolvers
# ---------------------------------------------------------------------------


def _resolve_graph(graph: Optional[nx.DiGraph] = None) -> nx.DiGraph:
    """Return *graph* or the singleton in-memory graph."""
    if graph is not None:
        return graph
    from graph.singleton import get_graph

    return get_graph()


def _resolve_tag_dag(tag_dag: Optional[nx.DiGraph] = None) -> nx.DiGraph:
    """Return *tag_dag* or the singleton ontology DAG."""
    if tag_dag is not None:
        return tag_dag
    from .dag import get_tag_dag

    return get_tag_dag()


def _get_theme_code_ids(graph: nx.DiGraph, theme_id: int) -> list[int]:
    """Return all code node IDs linked by ``composed-of`` edges from *theme_id*."""
    code_ids: list[int] = []
    for src, tgt, data in graph.edges(data=True):
        if data.get("type") != "composed-of":
            continue
        if src != theme_id:
            continue
        code_ids.append(tgt)
    return code_ids


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------


def validate_constraint(
    entity: dict[str, Any],
    action: str,
    graph: Optional[nx.DiGraph] = None,
    tag_dag: Optional[nx.DiGraph] = None,
) -> None:
    """Enforce ADR-013 structural invariants for *entity* and *action*.

    Args:
        entity: Dict describing the entity to validate. Required keys
            depend on the action:

            - ``approve``: ``{"id": ..., "type": "code"|"theme"}``
            - ``create`` (interpretation):
              ``{"type": "interpretation", "tag_spans": set[str]}``
            - ``merge``: ``{"id": ..., "type": ..., "tag": ...}``
            - ``assign_tag``: ``{"tag": "..."}``

        action: One of ``"approve"``, ``"create"``, ``"merge"``,
            ``"assign_tag"``.
        graph: In-memory DiGraph (codes/themes/interpretations + edges).
            Defaults to ``graph.singleton.get_graph()``.
        tag_dag: Ontology DAG (tag hierarchy). Defaults to
            ``ontology.dag.get_tag_dag()``.

    Raises:
        ConstraintError: On first rule violation.
        ValueError: For unknown actions.
    """
    resolved_graph = _resolve_graph(graph)
    resolved_tag_dag = _resolve_tag_dag(tag_dag)

    entity_type = entity.get("type", "")
    entity_id = entity.get("id")
    tag = entity.get("tag")
    tag_spans = entity.get("tag_spans")

    if action == "approve":
        if entity_type == "code" and entity_id is not None:
            validate_code_approval(entity_id, resolved_graph)
            validate_tag_exists(entity.get("tag", ""), resolved_tag_dag)
        elif entity_type == "theme" and entity_id is not None:
            validate_theme_approval(entity_id, resolved_graph)
            validate_theme_interpretation(entity_id, resolved_graph)
            # Each code in the theme must not already belong to an approved theme
            for code_id in _get_theme_code_ids(resolved_graph, entity_id):
                validate_code_approval(code_id, resolved_graph)
        elif entity_type == "interpretation" and tag_spans is not None:
            validate_interpretation_contiguity(tag_spans, resolved_tag_dag)

    elif action == "create":
        if entity_type == "interpretation" and tag_spans is not None:
            for t in tag_spans:
                validate_tag_exists(t, resolved_tag_dag)
            validate_interpretation_contiguity(tag_spans, resolved_tag_dag)

    elif action == "merge":
        if tag:
            validate_tag_exists(tag, resolved_tag_dag)
        if tag_spans:
            validate_interpretation_contiguity(tag_spans, resolved_tag_dag)
        validate_no_cycle(resolved_graph)

    elif action == "assign_tag":
        if tag:
            validate_tag_exists(tag, resolved_tag_dag)

    else:
        raise ValueError(f"Unknown constraint action: {action}")
