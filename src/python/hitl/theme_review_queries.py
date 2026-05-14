"""Database queries for theme review HITL CLI.

Provides ``_get_pending_themes``, ``_get_constituent_codes``,
``_get_theme_neighbors``, ``_get_available_codes_for_tag``, and
``_get_other_draft_themes`` to fetch draft theme nodes, their
constituent codes, and semantic neighbors.
"""

import json
from typing import Any, Optional


def _get_pending_themes(
    con,
    tag: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Fetch all theme nodes in ``draft`` status, ordered by id.

    If *tag* is provided, only themes for that tag are returned.
    """
    if tag:
        rows = con.execute(
            "SELECT id, name, definition, tag, data_json, status "
            "FROM nodes WHERE type = 'theme' AND status = 'draft' AND tag = ? "
            "ORDER BY id",
            [tag],
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT id, name, definition, tag, data_json, status "
            "FROM nodes WHERE type = 'theme' AND status = 'draft' ORDER BY id"
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
                "narrative": row[2],
                "tag": row[3],
                "data_json": dj,
                "status": row[5],
            }
        )
    return results


def _get_constituent_codes(
    con,
    theme_id: int,
) -> list[dict[str, Any]]:
    """Fetch codes linked by ``composed-of`` edges from a theme.

    Returns list of dicts with keys: ``id``, ``name``, ``status``,
    ``exemplar_count``. Ordered by code id.
    """
    rows = con.execute(
        """
        SELECT n.id, n.name, n.status, n.data_json
        FROM edges e
        JOIN nodes n ON n.id = e.target_id
        WHERE e.source_id = ? AND e.edge_type = 'composed-of'
        ORDER BY n.id
        """,
        [theme_id],
    ).fetchall()

    results = []
    for row in rows:
        dj = {}
        if row[3] is not None:
            try:
                dj = json.loads(row[3])
            except (json.JSONDecodeError, TypeError):
                dj = {}
        exemplar_ids = dj.get("exemplar_ids", []) if isinstance(dj, dict) else []
        results.append(
            {
                "id": row[0],
                "name": row[1],
                "status": row[2],
                "exemplar_count": len(exemplar_ids),
            }
        )
    return results


def _get_theme_neighbors(
    con,
    theme_id: int,
    k: int = 3,
) -> list[tuple[int, float, str]]:
    """Fetch semantic neighbor themes with similarity scores and names.

    Returns list of ``(neighbor_id, similarity, name)`` tuples sorted by
    descending similarity.
    """
    from semantic.neighbors import find_neighbors

    raw = find_neighbors(entity_id=theme_id, entity_type="theme", con=con, k=k)
    if not raw:
        return []

    results: list[tuple[int, float, str]] = []
    for nid, score in raw:
        row = con.execute("SELECT name FROM nodes WHERE id = ?", [nid]).fetchone()
        name = row[0] if row else f"Node {nid}"
        results.append((nid, score, name))
    return results


def _get_available_codes_for_tag(
    con,
    tag: str,
) -> list[dict[str, Any]]:
    """Fetch all code nodes for *tag* with id, name, and status.

    Returns codes ordered by id. All statuses included so the researcher
    can see the full picture when editing theme composition.
    """
    rows = con.execute(
        "SELECT id, name, status FROM nodes "
        "WHERE type = 'code' AND tag = ? ORDER BY id",
        [tag],
    ).fetchall()
    return [{"id": r[0], "name": r[1], "status": r[2]} for r in rows]


def _get_other_draft_themes(
    con,
    theme_id: int,
    tag: str,
) -> list[dict[str, Any]]:
    """Fetch other draft theme nodes in the same tag for merge selection.

    Returns list of dicts with keys: ``id``, ``name``, ``code_ids``.
    """
    rows = con.execute(
        "SELECT id, name, data_json FROM nodes "
        "WHERE type = 'theme' AND status = 'draft' AND tag = ? AND id != ? "
        "ORDER BY name",
        [tag, theme_id],
    ).fetchall()
    results = []
    for row in rows:
        dj = {}
        if row[2] is not None:
            try:
                dj = json.loads(row[2])
            except (json.JSONDecodeError, TypeError):
                dj = {}
        code_ids = dj.get("code_ids", []) if isinstance(dj, dict) else []
        results.append(
            {
                "id": row[0],
                "name": row[1],
                "code_ids": code_ids,
            }
        )
    return results
