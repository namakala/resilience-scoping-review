"""Constant values for workflow state management."""

WORKFLOW_KEY = "workflow"

DEFAULT_STATE = {
    "current_stage": 1,
    "dirty_flags": {},
    "last_checkpoint": None,
    "config_version": "",
    "user_action_count": 0,
}
