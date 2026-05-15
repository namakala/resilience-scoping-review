"""Code-specific database queries for HITL review."""

from typing import Any

from .queries import _get_neighbors, _parse_json


def get_neighbors_code(con, code_id: int, k: int = 5) -> list[tuple[int, float, str]]:
    return _get_neighbors(con, code_id, "code", k=k)


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
