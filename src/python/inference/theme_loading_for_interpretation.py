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

from .theme_code_loading import _load_exemplar_content_map

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
    codes_detail : tuple[dict, ...]
        Per-code detail: each dict has keys ``name``, ``definition``,
        ``exemplar_ids``, ``exemplar_contents`` (list of content strings).
    """

    id: int
    tag: str
    theme_name: str
    narrative: str
    code_ids: list[str]
    codes_detail: tuple[dict, ...] = ()


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

    Each returned ``_ThemeRow`` includes ``codes_detail`` with code
    names, definitions, and exemplar content loaded from the Parquet
    store.
    """
    nodes = get_nodes_by_type_and_tag("theme", tag)
    if not nodes:
        return []

    approved_themes: list[dict] = []
    all_code_ids: set[int] = set()
    for n in sorted(nodes, key=lambda x: x["id"]):
        if n.get("status") != "approved":
            continue
        code_ids = _parse_code_ids(n)
        approved_themes.append(
            {
                "id": n["id"],
                "tag": tag,
                "theme_name": n.get("name") or "",
                "narrative": n.get("definition") or "",
                "code_ids": code_ids,
            }
        )
        all_code_ids.update(int(cid) for cid in code_ids if cid and cid.isdigit())

    # Load code nodes for all referenced codes within this tag
    code_nodes = get_nodes_by_type_and_tag("code", tag)
    code_map: dict[int, dict] = {n["id"]: n for n in code_nodes}

    # Collect all exemplar IDs across all referenced codes
    all_exemplar_ids: set[str] = set()
    for nid in all_code_ids:
        cn = code_map.get(nid)
        if cn is None:
            continue
        dj = cn.get("data_json") or {}
        if isinstance(dj, dict):
            all_exemplar_ids.update(str(eid) for eid in dj.get("exemplar_ids", []))

    # Bulk-load exemplar content from Parquet
    content_map = _load_exemplar_content_map(all_exemplar_ids)

    # Build results with codes_detail
    approved: list[_ThemeRow] = []
    for th in approved_themes:
        codes_detail: list[dict] = []
        for cid_str in th["code_ids"]:
            if not cid_str or not cid_str.isdigit():
                continue
            cid = int(cid_str)
            cn = code_map.get(cid)
            if cn is None:
                logger.warning(
                    "Code node %d referenced by theme '%s' not found for tag '%s'",
                    cid,
                    th["theme_name"],
                    tag,
                )
                continue
            dj = cn.get("data_json") or {}
            if isinstance(dj, dict):
                eids = dj.get("exemplar_ids", [])
            else:
                eids = []
            exemplar_id_strs = [str(eid) for eid in eids]
            contents = [content_map.get(eid, "") for eid in exemplar_id_strs]
            codes_detail.append(
                {
                    "name": cn.get("name", ""),
                    "definition": cn.get("definition", ""),
                    "exemplar_ids": exemplar_id_strs,
                    "exemplar_contents": contents,
                }
            )
        approved.append(
            _ThemeRow(
                id=th["id"],
                tag=tag,
                theme_name=th["theme_name"],
                narrative=th["narrative"],
                code_ids=th["code_ids"],
                codes_detail=tuple(codes_detail),
            )
        )

    logger.debug(
        "Loaded %d approved themes for tag '%s' with code details",
        len(approved),
        tag,
    )
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
