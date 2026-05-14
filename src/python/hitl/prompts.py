"""Shared prompt helpers for HITL review CLI.

Entity-specific prompts live in ``prompts_codes``, ``prompts_themes``,
and ``prompts_interpretations``.
"""

from typing import Optional


def prompt_edit_text(label: str, default: str = "") -> Optional[str]:
    """Prompt the user to edit a text value.

    Returns the updated text, or ``None`` if cancelled.
    """
    import questionary

    result = questionary.text(
        label,
        default=default,
        validate=lambda v: len(v.strip()) > 0 or f"{label} cannot be empty",
    ).ask()
    return result  # type: ignore[no-any-return]
