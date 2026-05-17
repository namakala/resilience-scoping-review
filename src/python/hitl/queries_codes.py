"""Code-specific database queries for HITL review."""

from typing import Any, Optional

from .queries import _get_neighbors, _parse_json


def get_neighbors_code(con, code_id: int, k: int = 5) -> list[tuple[int, float, str]]:
    return _get_neighbors(con, code_id, "code", k=k)


def get_all_codes(
    con,
    tag: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Fetch ALL code nodes regardless of status, ordered by id.

    If *tag* is provided, only codes for that tag are returned.
    Returns list of dicts with keys: id, name, definition, tag,
    data_json, status.
    """
    if tag:
        rows = con.execute(
            "SELECT id, name, definition, tag, data_json, status "
            "FROM nodes WHERE type = 'code' AND tag = ? "
            "ORDER BY id",
            [tag],
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT id, name, definition, tag, data_json, status "
            "FROM nodes WHERE type = 'code' ORDER BY id"
        ).fetchall()

    results = []
    for row in rows:
        dj = _parse_json(row[4])
        results.append(
            {
                "id": row[0],
                "name": row[1],
                "definition": row[2],
                "tag": row[3],
                "data_json": dj,
                "status": row[5],
            }
        )
    return results


def get_all_codes_for_tag(con, tag: str) -> list[dict[str, Any]]:
    """Convenience wrapper — all codes in *tag* regardless of status.

    Uses ``get_all_codes`` with the tag filter applied.
    """
    return get_all_codes(con, tag=tag)


def get_pending_codes(con) -> list[dict[str, Any]]:
    """Fetch all code nodes in ``draft`` status, ordered by id."""
    rows = con.execute(
        "SELECT id, name, definition, tag, data_json, status "
        "FROM nodes WHERE type = 'code' AND status = 'draft' ORDER BY id"
    ).fetchall()
    results = []
    for row in rows:
        dj = _parse_json(row[4])
        results.append(
            {
                "id": row[0],
                "name": row[1],
                "definition": row[2],
                "tag": row[3],
                "data_json": dj,
                "status": row[5],
            }
        )
    return results


def get_code_exemplar_ids(
    con,
    code_id: int,
) -> list[int]:
    """Fetch exemplar IDs from a code's ``data_json``.

    Returns list of integer exemplar IDs.  Empty list if none found.
    """
    row = con.execute(
        "SELECT data_json FROM nodes WHERE id = ? AND type = 'code'",
        [code_id],
    ).fetchone()
    if not row:
        return []
    dj = _parse_json(row[0])
    return [int(eid) for eid in (dj.get("exemplar_ids") or [])]


def get_code_exemplars_with_content(
    con,
    code_id: int,
    truncate: int = 80,
) -> list[dict[str, Any]]:
    """Fetch exemplars linked by ``contains`` edges, with truncated content.

    Returns list of dicts with keys: ``id``, ``content`` (truncated to
    *truncate* chars).  Used by the SplitModal to display candidate items.
    """
    import polars as pl
    from persistence.loaders import load_exemplars

    eids = get_code_exemplar_ids(con, code_id)
    if not eids:
        return []

    rows = (
        load_exemplars()
        .select(["id", "content"])
        .filter(pl.col("id").is_in(eids))
        .collect()
    )
    results = []
    for r in rows.iter_rows(named=True):
        content = r["content"] or ""
        if len(content) > truncate:
            content = content[:truncate] + "..."
        results.append({"id": r["id"], "content": content})
    return results


def get_code_exemplars(
    con,
    code_id: int,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Fetch exemplars linked by ``contains`` edges from a code.

    Returns list of dicts with keys: ``id``, ``content`` (truncated to
    80 chars for display). Limited to *limit* results.
    """
    rows = con.execute(
        """
        SELECT n.id, n.definition
        FROM edges e
        JOIN nodes n ON n.id = e.target_id
        WHERE e.source_id = ? AND e.edge_type = 'contains'
        ORDER BY n.id
        LIMIT ?
        """,
        [code_id, limit],
    ).fetchall()

    TRUNCATE = 80
    results = []
    for r in rows:
        content = r[1] or ""
        truncated = content[:TRUNCATE] + "..." if len(content) > TRUNCATE else content
        results.append({"id": r[0], "content": truncated})
    return results
