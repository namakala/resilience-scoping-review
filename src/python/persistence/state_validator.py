"""Validation logic for workflow state."""

from typing import Any, Dict

from utils.exceptions import StateError
from utils.logging import get_logger

logger = get_logger(__name__)


def validate_state(state: Dict[str, Any]) -> None:
    """Validate the workflow state dictionary.

    Checks required keys, types, and value constraints. Extra keys beyond
    the five required fields are allowed and preserved.

    Args:
        state: Workflow state dictionary to validate.

    Raises:
        StateError: If validation fails (invalid stage, malformed dirty_flags, etc.).
    """
    # current_stage: int in [1, 10]
    cs = state.get("current_stage")
    if not isinstance(cs, int) or isinstance(cs, bool) or not (1 <= cs <= 10):
        raise StateError(
            f"Invalid current_stage: {cs}. Must be an integer between 1 and 10."
        )

    # dirty_flags: dict with string keys and boolean values
    df = state.get("dirty_flags")
    if not isinstance(df, dict):
        raise StateError(f"dirty_flags must be a dict, got {type(df).__name__}")
    for tag, dirty in df.items():
        if not isinstance(tag, str):
            raise StateError(
                f"dirty_flags key must be str, got {type(tag).__name__}: {tag!r}"
            )
        if not isinstance(dirty, bool):
            raise StateError(
                f"dirty_flags['{tag}'] must be bool, got {type(dirty).__name__}"
            )

    # last_checkpoint: None or string
    lc = state.get("last_checkpoint")
    if lc is not None and not isinstance(lc, str):
        raise StateError(
            f"last_checkpoint must be a string or None, got {type(lc).__name__}"
        )

    # config_version: string
    cv = state.get("config_version")
    if not isinstance(cv, str):
        raise StateError(f"config_version must be a string, got {type(cv).__name__}")

    # user_action_count: non-negative int
    uac = state.get("user_action_count")
    if not isinstance(uac, int) or isinstance(uac, bool) or uac < 0:
        raise StateError(f"user_action_count must be a non-negative int, got {uac!r}")

    logger.debug("State validation passed", extra={"stage": cs})
