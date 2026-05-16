"""Theme-specific database queries for HITL review."""

from typing import Any, Optional

from .queries import _get_neighbors, _parse_json


def get_neighbors_theme(con, theme_id: int, k: int = 3) -> list[tuple[int, float, str]]:
    return _get_neighbors(con, theme_id, "theme", k=k)


def get_all_themes(
    con,
    tag: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Fetch ALL theme nodes regardless of status, ordered by id.

    If *tag* is provided, only themes for that tag are returned.
    Returns list of dicts with keys: id, name, narrative, tag,
    data_json, status.
    """
    if tag:
        rows = con.execute(
            "SELECT id, name, definition, tag, data_json, status "
            "FROM nodes WHERE type = 'theme' AND tag = ? "
            "ORDER BY id",
            [tag],
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT id, name, definition, tag, data_json, status "
            "FROM nodes WHERE type = 'theme' ORDER BY id"
        ).fetchall()

    results = []
    for row in rows:
        dj = _parse_json(row[4])
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


def get_all_themes_for_tag(con, tag: str) -> list[dict[str, Any]]:
    """Convenience wrapper — all themes in *tag* regardless of status.

    Uses ``get_all_themes`` with the tag filter applied.
    """
    return get_all_themes(con, tag=tag)


def get_pending_themes(
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
        dj = _parse_json(row[4])
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


def get_constituent_codes(con, theme_id: int) -> list[dict[str, Any]]:
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
        dj = _parse_json(row[3])
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


def get_available_codes_for_tag(con, tag: str) -> list[dict[str, Any]]:
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


def get_other_draft_themes(
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
        dj = _parse_json(row[2])
        code_ids = dj.get("code_ids", []) if isinstance(dj, dict) else []
        results.append(
            {
                "id": row[0],
                "name": row[1],
                "code_ids": code_ids,
            }
        )
    return results


def get_theme_codes(con, theme_id: int) -> list[dict[str, Any]]:
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
