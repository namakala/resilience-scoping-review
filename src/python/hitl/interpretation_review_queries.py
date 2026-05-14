"""Database queries for interpretation review HITL CLI.

Provides ``_get_pending_interpretations``, ``_get_interpretation_themes``,
``_get_theme_codes``, ``_get_code_exemplars``, and
``_get_interpretation_neighbors`` to fetch draft interpretation nodes,
their constituent themes, codes, and exemplar evidence.
"""

import json
from typing import Any, Optional


def _get_pending_interpretations(
    con,
    tag: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Fetch all interpretation nodes in ``draft`` status, ordered by id.

    If *tag* is provided, only interpretations whose ``tag_spans``
    include that tag are returned (filtered in Python since tag_spans
    is stored in data_json).

    Returns list of dicts with keys: ``id``, ``name``, ``narrative``,
    ``tag``, ``data_json``, ``status``.
    """
    rows = con.execute(
        "SELECT id, name, definition, tag, data_json, status "
        "FROM nodes WHERE type = 'interpretation' AND status = 'draft' "
        "ORDER BY id"
    ).fetchall()

    results = []
    for row in rows:
        dj = {}
        if row[4] is not None:
            try:
                dj = json.loads(row[4])
            except (json.JSONDecodeError, TypeError):
                dj = {}
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


def _get_interpretation_themes(
    con,
    interp_id: int,
) -> list[dict[str, Any]]:
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


def _get_theme_codes(
    con,
    theme_id: int,
) -> list[dict[str, Any]]:
    """Fetch codes linked by ``composed-of`` edges from a theme.

    Returns list of dicts with keys: ``id``, ``name``, ``definition``,
    ``status``, ``tag``. Ordered by code id.
    """
    rows = con.execute(
        """
        SELECT n.id, n.name, n.definition, n.status, n.tag
        FROM edges e
        JOIN nodes n ON n.id = e.target_id
        WHERE e.source_id = ? AND e.edge_type = 'composed-of'
        ORDER BY n.id
        """,
        [theme_id],
    ).fetchall()

    return [
        {
            "id": r[0],
            "name": r[1],
            "definition": r[2],
            "status": r[3],
            "tag": r[4],
        }
        for r in rows
    ]


def _get_code_exemplars(
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


def _get_interpretation_neighbors(
    con,
    interp_id: int,
    k: int = 3,
) -> list[tuple[int, float, str]]:
    """Fetch semantic neighbor interpretations with similarity scores.

    Returns list of ``(neighbor_id, similarity, name)`` tuples sorted by
    descending similarity.
    """
    from semantic.neighbors import find_neighbors

    raw = find_neighbors(
        entity_id=interp_id, entity_type="interpretation", con=con, k=k
    )
    if not raw:
        return []

    results: list[tuple[int, float, str]] = []
    for nid, score in raw:
        row = con.execute("SELECT name FROM nodes WHERE id = ?", [nid]).fetchone()
        name = row[0] if row else f"Node {nid}"
        results.append((nid, score, name))
    return results
