"""Embedding invalidation for code edit and merge operations.

Provides ``invalidate_code_embedding`` — a centralized function that
deletes the embedding cache entry for a code and sets the dirty flag
for its tag branch, triggering re-embedding on the next pipeline run.
"""

import duckdb
from persistence.embedding_cache import invalidate_entity
from persistence.state_updates import update_dirty_flag
from utils.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "invalidate_code_embedding",
    "invalidate_theme_embedding",
]


def invalidate_code_embedding(
    con: duckdb.DuckDBPyConnection,
    code_id: int,
    tag: str,
) -> None:
    """Invalidate a code's embedding cache and mark its tag branch as dirty.

    Called after a code edit or merge to ensure the next pipeline run
    regenerates the embedding for this code and re-processes its tag.

    Args:
        con: Active DuckDB connection.
        code_id: ID of the code node.
        tag: Ontology tag associated with the code (e.g. ``"Problem.Cause"``).
    """
    invalidate_entity(con, str(code_id), "code")
    if tag:
        update_dirty_flag(con, tag)
    logger.debug(
        "Code embedding invalidated",
        extra={"code_id": code_id, "tag": tag},
    )


def invalidate_theme_embedding(
    con: duckdb.DuckDBPyConnection,
    theme_id: int,
    tag: str,
) -> None:
    """Invalidate a theme's embedding cache and mark its tag branch as dirty.

    Called after a theme edit or merge to ensure the next pipeline run
    regenerates the embedding for this theme and re-processes its tag.

    Args:
        con: Active DuckDB connection.
        theme_id: ID of the theme node.
        tag: Ontology tag associated with the theme.
    """
    invalidate_entity(con, str(theme_id), "theme")
    if tag:
        update_dirty_flag(con, tag)
    logger.debug(
        "Theme embedding invalidated",
        extra={"theme_id": theme_id, "tag": tag},
    )
