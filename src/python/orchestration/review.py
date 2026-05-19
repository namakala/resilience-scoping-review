"""Review utilities — HITL review entry points used by ``runner.py``.

Provides ``enter_review()`` for dispatching to type-specific review modules.
Not a standalone CLI command — HITL review is handled within the ``run``
subcommand via ``--tui``/``--no-tui`` flags.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

# ── Public dispatch (used by runner.py) ─────────────────────────────────────


def enter_review(con, review_type: Optional[str], db_path: Path) -> None:
    """Dispatch to the appropriate HITL review module."""
    if review_type is None or review_type == "code":
        _try_review_codes(con, db_path)
    if review_type is None or review_type == "theme":
        _try_review_themes(con, db_path)
    if review_type is None or review_type == "interpretation":
        _try_review_interpretations(con, db_path)


# ── Private review dispatchers ──────────────────────────────────────────────


def _try_review_codes(con, db_path: Path) -> None:
    """Run code review if there are pending codes."""
    from hitl.code_review import review_codes as hitl_review_codes

    click.echo("\n--- Code Review ---")
    hitl_review_codes(con, db_path=db_path)


def _try_review_themes(con, db_path: Path) -> None:
    """Run theme review if there are pending themes."""
    from hitl.theme_review import review_themes as hitl_review_themes

    click.echo("\n--- Theme Review ---")
    hitl_review_themes(con, db_path=db_path)


def _try_review_interpretations(con, db_path: Path) -> None:
    """Run interpretation review if there are pending interpretations."""
    from hitl.interpretation_review import (
        review_interpretations as hitl_review_interpretations,
    )

    click.echo("\n--- Interpretation Review ---")
    hitl_review_interpretations(con, db_path=db_path)


__all__ = ["enter_review"]
