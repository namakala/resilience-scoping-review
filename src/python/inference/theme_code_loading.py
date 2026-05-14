"""Load approved code nodes from the graph for theme inference.

Provides :func:`load_approved_codes` for single-tag lookup and
:func:`load_approved_codes_grouped` for multi-tag with tag discovery.

Usage:
    from inference.theme_code_loading import load_approved_codes

    codes = load_approved_codes("Problem.Cause")
    codes_by_tag = load_approved_codes_grouped(con)
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
from graph import get_nodes_by_type_and_tag
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = ["_CodeRow", "load_approved_codes", "load_approved_codes_grouped"]


@dataclass(frozen=True)
class _CodeRow:
    id: int
    tag: str
    name: str
    definition: str
    exemplar_count: int


def load_approved_codes(tag: str) -> list[_CodeRow]:
    """Fetch all approved code nodes for *tag* as ``_CodeRow`` items.

    ``exemplar_count`` is derived from ``data_json["exemplar_ids"]``
    length (list of exemplar IDs supporting this code).
    """
    nodes = get_nodes_by_type_and_tag("code", tag)
    approved: list[_CodeRow] = []
    for n in sorted(nodes, key=lambda x: x["id"]):
        if n.get("status") != "approved":
            continue
        dj = n.get("data_json") or {}
        if isinstance(dj, dict):
            exemplar_ids = dj.get("exemplar_ids", [])
        else:
            exemplar_ids = []
        approved.append(
            _CodeRow(
                id=n["id"],
                tag=tag,
                name=n["name"] or "",
                definition=n["definition"] or "",
                exemplar_count=len(exemplar_ids),
            )
        )
    logger.debug("Loaded %d approved codes for tag '%s'", len(approved), tag)
    return approved


def load_approved_codes_grouped(
    con: duckdb.DuckDBPyConnection,
    tag: str | None = None,
) -> dict[str, list[_CodeRow]]:
    """Return ``{tag: [approved_codes]}`` grouped by ontology tag.

    If *tag* is provided, only that tag is queried.  Otherwise discovers
    all tags that have approved code nodes via a ``DISTINCT tag`` lookup
    on the ``nodes`` table.
    """
    if tag:
        codes = load_approved_codes(tag)
        return {tag: codes} if codes else {}

    rows = con.execute(
        "SELECT DISTINCT tag FROM nodes "
        "WHERE type = 'code' AND status = 'approved' "
        "ORDER BY tag"
    ).fetchall()
    tags = [r[0] for r in rows]
    result: dict[str, list[_CodeRow]] = {}
    for t in tags:
        codes = load_approved_codes(t)
        if codes:
            result[t] = codes
    return result
