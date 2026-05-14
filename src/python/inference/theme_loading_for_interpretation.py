"""Load approved theme nodes from the graph for interpretation synthesis.

Provides :func:`load_approved_themes` for single-tag lookup and
:func:`load_approved_themes_grouped` for multi-tag by span.

Usage:
    from inference.theme_loading_for_interpretation import load_approved_themes

    themes = load_approved_themes("Problem.Cause")
    themes_by_tag = load_approved_themes_grouped({"A", "A.B"})
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from graph import get_nodes_by_type_and_tag
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = ["_ThemeRow", "load_approved_themes", "load_approved_themes_grouped"]


@dataclass(frozen=True)
class _ThemeRow:
    """A single approved theme node loaded from the graph.

    Attributes
    ----------
    id : int
        Graph node ID.
    tag : str
        Ontology tag the theme belongs to.
    theme_name : str
        Theme name.
    narrative : str
        Theme narrative / definition.
    code_ids : list[str]
        Code IDs referenced by this theme (from data_json).
    """

    id: int
    tag: str
    theme_name: str
    narrative: str
    code_ids: list[str]


def _parse_code_ids(node: dict) -> list[str]:
    """Extract ``code_ids`` from a theme node's ``data_json``."""
    dj = node.get("data_json") or {}
    if isinstance(dj, str):
        try:
            dj = json.loads(dj)
        except (json.JSONDecodeError, TypeError):
            return []
    raw = dj.get("code_ids", []) if isinstance(dj, dict) else []
    return [str(cid) for cid in raw]


def load_approved_themes(tag: str) -> list[_ThemeRow]:
    """Fetch all approved theme nodes for *tag*.

    Queries the ``nodes`` table for ``type='theme'`` with
    ``status='approved'``. Returns an empty list when no approved
    themes exist for the tag.
    """
    nodes = get_nodes_by_type_and_tag("theme", tag)
    approved: list[_ThemeRow] = []
    for n in sorted(nodes, key=lambda x: x["id"]):
        if n.get("status") != "approved":
            continue
        approved.append(
            _ThemeRow(
                id=n["id"],
                tag=tag,
                theme_name=n.get("name") or "",
                narrative=n.get("definition") or "",
                code_ids=_parse_code_ids(n),
            )
        )
    logger.debug("Loaded %d approved themes for tag '%s'", len(approved), tag)
    return approved


def load_approved_themes_grouped(tags: set[str]) -> dict[str, list[_ThemeRow]]:
    """Return ``{tag: [approved_themes]}`` for each tag in *tags*.

    Skips tags with zero approved themes (logs a debug message).
    """
    result: dict[str, list[_ThemeRow]] = {}
    for t in sorted(tags):
        themes = load_approved_themes(t)
        if themes:
            result[t] = themes
    if not result:
        logger.debug("No approved themes found for any tag in %s", sorted(tags))
    return result
