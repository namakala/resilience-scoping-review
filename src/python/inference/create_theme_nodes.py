"""Convert ``ThemeInference`` results into graph theme nodes with edges.

For each :class:`~inference.parsing.ThemeInference` item creates:

- A ``theme`` graph node (type='theme', status='draft')
- A ``composed-of`` edge from the theme node to each referenced code node

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
from graph import create_edge, create_node, graph_transaction
from utils.logging import get_logger

from .inference_status_crud import set_status
from .inference_status_types import ENTITY_THEME, GENERATED, STAGE_THEME
from .parsing import ThemeInference

logger = get_logger(__name__)

__all__ = ["create_theme_nodes"]


def _build_data_json(theme: ThemeInference) -> dict:
    """Build the ``data_json`` payload for a theme node."""
    return {"code_ids": theme.code_ids}


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

    data_tags = f" for tag '{tag}'" if tag else ""
    logger.info(
        "Creating %d theme nodes%s",
        len(themes),
        data_tags,
    )

    node_ids: list[int] = []
    with graph_transaction(db_path=db_path):
        for theme in themes:
            data_json = _build_data_json(theme)
            node_id = create_node(
                node_type="theme",
                name=theme.theme_name,
                definition=theme.narrative,
                tag=tag,
                status="draft",
                data_json=data_json,
                db_path=db_path,
            )
            node_ids.append(node_id)

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
                create_edge(
                    source_id=node_id,
                    target_id=code_id,
                    edge_type="composed-of",
                    db_path=db_path,
                )

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
