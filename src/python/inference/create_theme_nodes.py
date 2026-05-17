"""Convert ``ThemeInference`` results into graph theme nodes with edges.

For each :class:`~inference.parsing.ThemeInference` item creates:

- A ``theme`` graph node (type='theme', status='draft')
- A ``composed-of`` edge from the theme node to each referenced code node
- If a draft theme with the same name exists (re-inference), the old node
  is renamed and a ``derived-from`` edge links old → new.

All graph writes within a single
:class:`~graph.transactions.graph_transaction` for atomicity.

Usage:
    from inference.create_theme_nodes import create_theme_nodes

    themes = infer_themes(con, tag="T1")
    node_ids = create_theme_nodes(con, themes, tag="T1")
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb
from graph import create_edge, create_node, get_nodes_by_type_and_tag, graph_transaction
from graph.transactions import get_active_connection
from utils.logging import get_logger

from .inference_status_crud import set_status
from .inference_status_types import ENTITY_THEME, GENERATED, STAGE_THEME
from .name_utils import check_duplicate_theme_names, make_unique_name
from .parsing import ThemeInference
from .theme_node_reinfer import rename_node_raw

logger = get_logger(__name__)

__all__ = ["create_theme_nodes"]


def _build_data_json(theme: ThemeInference) -> dict:
    """Build the ``data_json`` payload for a theme node."""
    return {"code_ids": theme.code_ids}


def _code_has_existing_theme(
    code_id: int,
    db_path: Optional[Path] = None,
) -> bool:
    """Check if *code_id* already has a ``composed-of`` edge from a non-merged theme.

    Must be called inside a :class:`graph_transaction` context.
    Returns ``True`` if the code already belongs to a draft or approved theme.
    """
    con = get_active_connection()
    if con is None:
        logger.warning(
            "_code_has_existing_theme called outside graph_transaction; "
            "skipping check for code %d",
            code_id,
        )
        return False
    row = con.execute(
        "SELECT 1 FROM edges e "
        "JOIN nodes n ON n.id = e.source_id "
        "WHERE e.target_id = ? AND e.edge_type = 'composed-of' "
        "AND n.status != 'merged' "
        "LIMIT 1",
        [code_id],
    ).fetchone()
    return row is not None


def _load_all_theme_names(
    db_path: Optional[Path] = None,
) -> set[str]:
    """Fetch ALL existing theme node names across all tags.

    Used for cross-tag collision detection.
    """
    nodes = get_nodes_by_type_and_tag("theme", None, db_path=db_path)
    return {n["name"] for n in nodes}


def create_theme_nodes(
    con: duckdb.DuckDBPyConnection,
    themes: list[ThemeInference],
    tag: str,
    db_path: Optional[Path] = None,
) -> list[int]:
    """Convert *themes* into graph nodes with ``composed-of`` edges.

    For each :class:`ThemeInference` item:

    1. Creates a ``theme`` graph node (type='theme', status='draft')
    2. Creates a ``composed-of`` edge from the theme node to each
       referenced code node.
    3. If a draft theme node with the same ``theme_name`` already
       exists in the same tag (re-inference), the existing node is
       renamed to ``{name}_deprecated_{id}`` and a ``derived-from``
       edge is created from the old node to the new node.

    All graph mutations are wrapped in a single
    :class:`~graph.transactions.graph_transaction` for atomicity.
    After the transaction succeeds, each theme entity's
    ``inference_status`` is set to ``generated``.

    Args:
        con: Active DuckDB connection (used for inference_status
            updates after graph transaction).
        themes: List of :class:`ThemeInference` items.
        tag: Ontology tag shared by all themes (every code in every
            theme must belong to this tag).
        db_path: Optional DuckDB path for graph module.

    Returns:
        List of created theme node IDs in the same order as *themes*.

    Raises:
        ValueError: If *themes* is empty, or if a theme has no name
            or no ``code_ids``.
    """
    # ── Input validation ───────────────────────────────────────────────
    if not themes:
        logger.warning("create_theme_nodes called with empty list; no-op")
        return []

    if not tag:
        raise ValueError("'tag' parameter must be a non-empty string")

    for t in themes:
        if not t.theme_name:
            raise ValueError(f"ThemeInference has empty theme_name: {t}")
        if not t.code_ids:
            logger.warning(
                "Theme '%s' has no code_ids; creating node anyway",
                t.theme_name,
            )

    # Warn about duplicate names within the same batch (HITL merge later)
    check_duplicate_theme_names(themes)

    # ── Pre-transaction: detect re-inference candidates ────────────────
    from graph.queries import load_occupied_names
    from persistence.state_constants import NON_APPROVED_STATUSES

    occupied = load_occupied_names(
        "theme", tag=tag, statuses=NON_APPROVED_STATUSES, db_path=db_path
    )

    superseded_names: set[str] = {
        th.theme_name for th in themes if th.theme_name in occupied
    }

    used_names: set[str] = {n for n in occupied if n not in superseded_names}

    data_tags = f" for tag '{tag}'" if tag else ""
    logger.info(
        "Creating %d theme nodes%s%s",
        len(themes),
        data_tags,
        f" ({len(superseded_names)} re-inferred)" if superseded_names else "",
    )

    # ── Transaction: rename superseded + create new ────────────────────
    node_ids: list[int] = []
    with graph_transaction(db_path=db_path):
        for theme in themes:
            if theme.theme_name in superseded_names:
                old_id = occupied[theme.theme_name]
                old_name = f"{theme.theme_name}_deprecated_{old_id}"
                rename_node_raw(old_id, old_name, db_path=db_path)
                logger.info(
                    "Superseded draft theme '%s' (id=%d) renamed to '%s'",
                    theme.theme_name,
                    old_id,
                    old_name,
                )

        # Cross-tag collision safety net: draft/approved themes from other tags
        other_tag_names = set()
        for n in get_nodes_by_type_and_tag("theme", None, db_path=db_path):
            if n.get("tag") != tag and n.get("status") in ("draft", "approved"):
                other_tag_names.add(n["name"])

        for theme in themes:
            unique_name = make_unique_name(
                theme.theme_name, used_names, entity_type="theme"
            )

            # Cross-tag collision safety net: only check OTHER tags
            if unique_name in other_tag_names:
                qualified = f"{unique_name} [{tag}]"
                logger.warning(
                    "Cross-tag theme name collision '%s' resolved to '%s'",
                    unique_name,
                    qualified,
                )
                unique_name = make_unique_name(qualified, other_tag_names)

            used_names.add(unique_name)

            data_json = _build_data_json(theme)
            node_id = create_node(
                node_type="theme",
                name=unique_name,
                definition=theme.narrative,
                tag=tag,
                status="draft",
                data_json=data_json,
                db_path=db_path,
            )
            node_ids.append(node_id)

            prev_id = occupied.get(theme.theme_name)
            if prev_id is not None:
                create_edge(
                    source_id=prev_id,
                    target_id=node_id,
                    edge_type="derived-from",
                    db_path=db_path,
                )

            for code_id_str in theme.code_ids:
                try:
                    code_id = int(code_id_str)
                except (ValueError, TypeError):
                    logger.error(
                        "Invalid code_id '%s' in theme '%s'; skipping edge",
                        code_id_str,
                        theme.theme_name,
                    )
                    continue
                if _code_has_existing_theme(code_id, db_path=db_path):
                    logger.warning(
                        "Code %d already belongs to another theme; "
                        "skipping composed-of edge from theme '%s'",
                        code_id,
                        theme.theme_name,
                    )
                    continue
                create_edge(
                    source_id=node_id,
                    target_id=code_id,
                    edge_type="composed-of",
                    db_path=db_path,
                )

    # ── Post-transaction: update inference_status ──────────────────────
    for node_id in node_ids:
        set_status(
            con,
            entity_id=str(node_id),
            entity_type=ENTITY_THEME,
            stage=STAGE_THEME,
            status=GENERATED,
        )

    logger.info(
        "Created %d theme nodes for tag '%s'",
        len(node_ids),
        tag,
    )
    return node_ids
