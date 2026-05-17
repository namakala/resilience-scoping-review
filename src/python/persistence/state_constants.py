"""Constant values for workflow state management."""

WORKFLOW_KEY = "workflow"

DEFAULT_STATE = {
    "current_stage": 1,
    "dirty_flags": {},
    "last_checkpoint": None,
    "config_version": "",
    "user_action_count": 0,
}

# Statuses that occupy the name namespace but are not finalised
# (excludes ``approved`` and ``immutable`` which should not be
# overwritten by re-inference).  Includes ``superseded`` which
# is set on split originals.
NON_APPROVED_STATUSES = frozenset({"draft", "merged", "rejected", "superseded"})
