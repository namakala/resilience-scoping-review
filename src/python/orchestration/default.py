"""Default handler — invoked when no subcommand is given.

Checks for existing codes, prompts to generate if none exist,
otherwise enters the pipeline runner which will launch the TUI
or CLI review as appropriate.
"""

from __future__ import annotations

import click


def handle_default(obj: dict) -> None:
    """Default entry when no subcommand is given.

    Delegates to ``run_sequence`` which auto-detects interactive mode
    and launches the TUI or CLI review as appropriate.
    """
    click.echo("Connecting to session...")
    from orchestration.run import run_sequence

    run_sequence(("code", "theme", "interpretation"), ctx_obj=obj)


__all__ = ["handle_default"]
