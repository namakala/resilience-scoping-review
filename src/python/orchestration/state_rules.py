"""Stage constants and field validation for WorkflowState.

One-way dependency: state.py imports this module. This module must
never import WorkflowState (circular dependency prevention).
"""

from typing import Any, Dict

from utils.exceptions import StateError

MIN_STAGE = 1  # Earliest pipeline stage (Load).

MAX_STAGE = 10  # Final pipeline stage (Export).

STAGE_PREREQS: Dict[int, list[int]] = {
    2: [1],
    3: [2],
    4: [3],
    5: [4],
    6: [5],
    7: [6],
    8: [7],
    9: [8],
    10: [9],
}  # Linear stage adjacency: each stage requires the previous.


def validate_state_fields(
    current_stage: Any,
    dirty_flags: Any,
    last_checkpoint: Any,
    config_version: Any,
    user_action_count: Any,
) -> None:
    """Validate WorkflowState field values. Raises StateError if
    any field is of the wrong type or out of range."""
    if (
        not isinstance(current_stage, int)
        or isinstance(current_stage, bool)
        or not (MIN_STAGE <= current_stage <= MAX_STAGE)
    ):
        raise StateError(
            f"current_stage must be an int between "
            f"{MIN_STAGE} and {MAX_STAGE}, "
            f"got {current_stage!r}"
        )

    if not isinstance(dirty_flags, dict):
        raise StateError(
            f"dirty_flags must be a dict, " f"got {type(dirty_flags).__name__}"
        )
    for tag, dirty in dirty_flags.items():
        if not isinstance(tag, str):
            raise StateError(
                f"dirty_flags key must be str, " f"got {type(tag).__name__}: {tag!r}"
            )
        if not isinstance(dirty, bool):
            raise StateError(
                f"dirty_flags['{tag}'] must be bool, " f"got {type(dirty).__name__}"
            )

    if last_checkpoint is not None and not isinstance(last_checkpoint, str):
        raise StateError(
            f"last_checkpoint must be str or None, "
            f"got {type(last_checkpoint).__name__}"
        )

    if not isinstance(config_version, str):
        raise StateError(
            f"config_version must be a string, " f"got {type(config_version).__name__}"
        )

    if (
        not isinstance(user_action_count, int)
        or isinstance(user_action_count, bool)
        or user_action_count < 0
    ):
        raise StateError(
            f"user_action_count must be a non-negative "
            f"int, got {user_action_count!r}"
        )
