"""Nodes: HITL review passthroughs and edit-apply stubs.

Review functions are identity passthroughs — the orchestration layer provides
overrides with user-approved data via Hamilton's ``overrides`` mechanism.
Edit-apply stubs merge edit diffs.
"""

from __future__ import annotations

from pipeline.config import Config

__all__ = [
    "review_codes",
    "review_themes",
    "review_interpretations",
    "apply_code_edits",
    "apply_theme_edits",
    "apply_interpretation_edits",
]


def review_codes(infer_codes: list, config: Config) -> list:
    """Passthrough — orchestration provides HITL-approved codes as override."""
    return infer_codes


def review_themes(infer_themes: list, config: Config) -> list:
    """Passthrough — orchestration provides HITL-approved themes as override."""
    return infer_themes


def review_interpretations(infer_interpretations: list, config: Config) -> list:
    """Passthrough — orchestration provides HITL-approved interpretations."""
    return infer_interpretations


def apply_code_edits(review_codes: list, config: Config) -> list:
    """Apply edit diffs to codes.  Stub: returns input unchanged."""
    return review_codes


def apply_theme_edits(review_themes: list, config: Config) -> list:
    """Apply edit diffs to themes.  Stub: returns input unchanged."""
    return review_themes


def apply_interpretation_edits(review_interpretations: list, config: Config) -> list:
    """Apply edit diffs to interpretations.  Stub: returns input unchanged."""
    return review_interpretations
