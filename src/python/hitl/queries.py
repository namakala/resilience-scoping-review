"""Database queries for HITL review modules.

Consolidated from per-entity query files.  Neighbor queries are
parameterized by entity type; entity-specific wrappers are provided
for backward compatibility.
"""

import json
from typing import Any, Optional

# ── Shared neighbor query helper ────────────────────────────────────


def _get_neighbors(
    con,
    entity_id: int,
    entity_type: str,
    k: int = 5,
) -> list[tuple[int, float, str]]:
    """Fetch semantic neighbors with similarity scores and names.

    Returns list of ``(neighbor_id, similarity, name)`` tuples sorted by
    descending similarity.
    """
    from semantic.neighbors import find_neighbors

    raw = find_neighbors(entity_id=entity_id, entity_type=entity_type, con=con, k=k)
    if not raw:
        return []

    results: list[tuple[int, float, str]] = []
    for nid, score in raw:
        row = con.execute("SELECT name FROM nodes WHERE id = ?", [nid]).fetchone()
        name = row[0] if row else f"Node {nid}"
        results.append((nid, score, name))
    return results


# ── Entity-specific neighbor wrappers ───────────────────────────────


def _get_neighbors_code(con, code_id: int, k: int = 5) -> list[tuple[int, float, str]]:
    return _get_neighbors(con, code_id, "code", k=k)


def _get_neighbors_theme(
    con, theme_id: int, k: int = 3
) -> list[tuple[int, float, str]]:
    return _get_neighbors(con, theme_id, "theme", k=k)


def _get_neighbors_interpretation(
    con, interp_id: int, k: int = 3
) -> list[tuple[int, float, str]]:
    return _get_neighbors(con, interp_id, "interpretation", k=k)


# ── Pending entity queries ──────────────────────────────────────────


def _get_pending_codes(con) -> list[dict[str, Any]]:
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


def _get_pending_interpretations(
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


# ── Theme constituent queries ───────────────────────────────────────


def _get_constituent_codes(con, theme_id: int) -> list[dict[str, Any]]:
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


def _get_available_codes_for_tag(con, tag: str) -> list[dict[str, Any]]:
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


# ── Interpretation evidence queries ─────────────────────────────────


def _get_interpretation_themes(con, interp_id: int) -> list[dict[str, Any]]:
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


def _get_theme_codes(con, theme_id: int) -> list[dict[str, Any]]:
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


# ── JSON helper ─────────────────────────────────────────────────────


def _parse_json(value: Any) -> dict[str, Any]:
    """Safely parse a JSON column value to a dict.

    Returns empty dict for ``None``, decode errors, or non-dict values.
    """
    if value is None:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}
