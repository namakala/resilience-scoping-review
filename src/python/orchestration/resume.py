"""Session resume logic for the orchestration layer.

On ``--resume``, loads saved workflow state from DuckDB, validates
config version integrity, and returns the restored state.
Without ``--resume``, returns a fresh ``WorkflowState``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb
from orchestration.state import WorkflowState
from persistence.state_repository import load_state, reset_state
from utils.logging import get_logger

logger = get_logger(__name__)


def resolve_state(
    con: duckdb.DuckDBPyConnection,
    resume: bool = False,
    force_resume: bool = False,
    env_file: Optional[Path] = None,
) -> WorkflowState:
    """Determine the initial workflow state based on resume flags.

    *Fresh start* (``resume=False``) returns a default ``WorkflowState``
    with ``config_version`` set to the current config hash.

    *Resume* (``resume=True``) loads persisted state from DuckDB and
    validates that the stored ``config_version`` matches the current
    config hash.  If the config has changed and ``force_resume`` is not
    set, raises ``SystemExit(2)``.

    Args:
        con: Active DuckDB connection.
        resume: Whether ``--resume`` was passed.
        force_resume: Whether ``--force-resume`` was passed (skip config
            version check).
        env_file: Path to the ``--env`` file, if any (used for config
            hashing).

    Returns:
        ``WorkflowState`` ready for pipeline execution.

    Raises:
        SystemExit: If config version mismatch and ``--force-resume``
            not set.
    """
    if not resume:
        state = WorkflowState()
        _set_config_hash(state, env_file)
        return state

    state_dict = load_state(con)
    state = WorkflowState.from_state_dict(state_dict)

    current_hash = _compute_config_hash(env_file)
    stored_version = state.config_version

    if stored_version and current_hash and stored_version != current_hash:
        msg = (
            f"Configuration has changed since last session "
            f"(stored={stored_version[:16]}, current={current_hash[:16]}). "
            f"Use --force-resume to override or --no-resume to restart."
        )
        if not force_resume:
            logger.error(msg)
            raise SystemExit(2)
        logger.warning(f"{msg} Overriding with --force-resume.")

    logger.info(
        "Resuming from stage %d (checkpoint %s)",
        state.current_stage,
        state.last_checkpoint,
    )
    return state


def handle_reset(con: duckdb.DuckDBPyConnection) -> None:
    """Clear session state and log the action.

    After calling this the next pipeline run will start from stage 1.
    """
    reset_state(con)
    logger.info("Session state reset — next run will start from stage 1.")


def _set_config_hash(state: WorkflowState, env_file: Optional[Path] = None) -> None:
    """Compute the current config hash and store it on *state*."""
    h = _compute_config_hash(env_file)
    if h:
        state.config_version = h


def _compute_config_hash(env_file: Optional[Path] = None) -> str:
    """Compute a config hash from loaded env files.

    Hashes the default ``.env`` and optionally the ``--env`` override
    file.  Returns a 64-char hex digest or ``""`` if no files exist.
    """
    paths: list[Path] = []
    default_env = Path(".env")
    if default_env.exists():
        paths.append(default_env)
    if env_file is not None and env_file.exists() and env_file != default_env:
        paths.append(env_file)
    if not paths:
        return ""
    return WorkflowState.compute_config_hash(*paths)


__all__ = [
    "handle_reset",
    "resolve_state",
]
