"""Database queries for code review HITL CLI.

Provides ``_get_pending_codes`` and ``_get_neighbors`` to fetch
draft code nodes and their semantic neighbors.
"""

import json
from typing import Any


def _get_pending_codes(con) -> list[dict[str, Any]]:
    """Fetch all code nodes in ``draft`` status, ordered by id."""
    rows = con.execute(
        "SELECT id, name, definition, tag, data_json, status "
        "FROM nodes WHERE type = 'code' AND status = 'draft' ORDER BY id"
    ).fetchall()
    results = []
    for row in rows:
        dj = {}
        if row[4] is not None:
            try:
                dj = json.loads(row[4])
            except (json.JSONDecodeError, TypeError):
                dj = {}
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


def _get_neighbors(
    con,
    code_id: int,
    k: int = 5,
) -> list[tuple[int, float, str]]:
    """Fetch semantic neighbors with similarity scores and names.

    Returns list of ``(neighbor_id, similarity, name)`` tuples sorted by
    descending similarity.
    """
    from semantic.neighbors import find_neighbors

    raw = find_neighbors(entity_id=code_id, entity_type="code", con=con, k=k)
    if not raw:
        return []

    results: list[tuple[int, float, str]] = []
    for nid, score in raw:
        row = con.execute("SELECT name FROM nodes WHERE id = ?", [nid]).fetchone()
        name = row[0] if row else f"Node {nid}"
        results.append((nid, score, name))
    return results
