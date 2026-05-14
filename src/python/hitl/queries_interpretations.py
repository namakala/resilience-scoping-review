"""Interpretation-specific database queries for HITL review."""

from typing import Any, Optional

from .queries import _get_neighbors, _parse_json


def get_neighbors_interpretation(
    con, interp_id: int, k: int = 3
) -> list[tuple[int, float, str]]:
    return _get_neighbors(con, interp_id, "interpretation", k=k)


def get_pending_interpretations(
    con,
    tag: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Fetch all interpretation nodes in ``draft`` status, ordered by id.

    If *tag* is provided, only interpretations whose ``tag_spans``
    include that tag are returned (filtered in Python since tag_spans
    is stored in data_json).
    """
    rows = con.execute(
        "SELECT id, name, definition, tag, data_json, status "
        "FROM nodes WHERE type = 'interpretation' AND status = 'draft' "
        "ORDER BY id"
    ).fetchall()

    results = []
    for row in rows:
        dj = _parse_json(row[4])
        if tag is not None:
            tag_spans = dj.get("tag_spans") or []
            if tag not in tag_spans:
                continue
        results.append(
            {
                "id": row[0],
                "name": row[1],
                "narrative": row[2],
                "tag": row[3],
                "data_json": dj,
                "status": row[5],
            }
        )
    return results


def get_interpretation_themes(con, interp_id: int) -> list[dict[str, Any]]:
    """Fetch themes linked by ``spans`` edges from an interpretation.

    Returns list of dicts with keys: ``id``, ``name``, ``narrative``,
    ``tag``, ``status``. Ordered by theme id.
    """
    rows = con.execute(
        """
        SELECT n.id, n.name, n.definition, n.tag, n.status
        FROM edges e
        JOIN nodes n ON n.id = e.target_id
        WHERE e.source_id = ? AND e.edge_type = 'spans'
        ORDER BY n.id
        """,
        [interp_id],
    ).fetchall()

    return [
        {
            "id": r[0],
            "name": r[1],
            "narrative": r[2],
            "tag": r[3],
            "status": r[4],
        }
        for r in rows
    ]
