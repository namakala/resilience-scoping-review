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
import polars as pl
from graph import get_nodes_by_type_and_tag
from persistence.loaders import load_exemplars
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "_CodeRow",
    "_load_exemplar_content_map",
    "load_approved_codes",
    "load_approved_codes_grouped",
]


def _load_exemplar_content_map(exemplar_ids: set[str]) -> dict[str, str]:
    """Load exemplar content for given IDs from the Parquet store.

    Args:
        exemplar_ids: Set of exemplar ID strings. Non-integer IDs
            are silently skipped (logged at debug level).

    Returns:
        Dict mapping each found exemplar ID to its content string.
        Missing IDs are omitted (no error).
    """
    if not exemplar_ids:
        return {}

    int_ids: list[int] = []
    skipped: list[str] = []
    for x in exemplar_ids:
        if not x:
            continue
        try:
            int_ids.append(int(x))
        except (ValueError, TypeError):
            skipped.append(x)
    if skipped:
        logger.debug("Skipped non-integer exemplar IDs: %s", skipped)
    if not int_ids:
        return {}

    rows = (
        load_exemplars()
        .select(["id", "content"])
        .filter(pl.col("id").is_in(int_ids))
        .collect()
    )
    return {str(r["id"]): r["content"] for r in rows.iter_rows(named=True)}


@dataclass(frozen=True)
class _CodeRow:
    id: int
    tag: str
    name: str
    definition: str
    exemplar_count: int
    exemplar_contents: tuple[str, ...] = ()


def load_approved_codes(
    tag: str,
    code_ids: list[int] | None = None,
) -> list[_CodeRow]:
    """Fetch all approved code nodes for *tag* as ``_CodeRow`` items.

    When *code_ids* is provided, only those specific code IDs are
    loaded (must still have status ``approved``).  This scoped mode
    is used by split re-inference to process only the regrouped codes.

    ``exemplar_count`` is derived from ``data_json["exemplar_ids"]``
    length (list of exemplar IDs supporting this code).
    ``exemplar_contents`` is loaded from the Parquet store in a single
    batch query.
    """
    nodes = get_nodes_by_type_and_tag("code", tag)

    # Build ID set for optional scoping
    code_ids_set: set[int] | None = set(code_ids) if code_ids is not None else None

    approved: list[_CodeRow] = []
    # First pass: collect all exemplar IDs across all approved codes
    all_exemplar_ids: set[str] = set()
    code_exemplar_map: dict[int, list[str]] = {}
    for n in sorted(nodes, key=lambda x: x["id"]):
        if n.get("status") != "approved":
            continue
        if code_ids_set is not None and n["id"] not in code_ids_set:
            continue
        dj = n.get("data_json") or {}
        if isinstance(dj, dict):
            exemplar_ids = dj.get("exemplar_ids", [])
        else:
            exemplar_ids = []
        eids = [str(eid) for eid in exemplar_ids]
        code_exemplar_map[n["id"]] = eids
        all_exemplar_ids.update(eids)
    # Bulk-load exemplar content from Parquet
    content_map = _load_exemplar_content_map(all_exemplar_ids)
    for n in sorted(nodes, key=lambda x: x["id"]):
        if n.get("status") != "approved":
            continue
        eids = code_exemplar_map.get(n["id"], [])
        contents = tuple(content_map.get(eid, "") for eid in eids)
        approved.append(
            _CodeRow(
                id=n["id"],
                tag=tag,
                name=n["name"] or "",
                definition=n["definition"] or "",
                exemplar_count=len(eids),
                exemplar_contents=contents,
            )
        )
    logger.debug("Loaded %d approved codes for tag '%s'", len(approved), tag)
    return approved


def load_approved_codes_grouped(
    con: duckdb.DuckDBPyConnection,
    tag: str | None = None,
    code_ids: list[int] | None = None,
) -> dict[str, list[_CodeRow]]:
    """Return ``{tag: [approved_codes]}`` grouped by ontology tag.

    If *tag* is provided, only that tag is queried.  Otherwise discovers
    all tags that have approved code nodes via a ``DISTINCT tag`` lookup
    on the ``nodes`` table.

    When *code_ids* is provided (and *tag* is also given), only those
    specific code IDs are loaded.  This scoped mode is used by split
    re-inference.
    """
    if tag:
        codes = load_approved_codes(tag, code_ids=code_ids)
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
