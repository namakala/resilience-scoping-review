"""Shared database utilities for HITL review modules.

Provides ``_parse_json`` for safe JSON column parsing and
``_get_neighbors`` for parameterized semantic neighbor queries.
Entity-specific queries live in ``queries_codes``, ``queries_themes``,
and ``queries_interpretations``.
"""

import json
from typing import Any


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
