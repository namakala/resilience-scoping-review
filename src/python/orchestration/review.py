"""Review subcommand — standalone click command registered via ``cli.add_command``.

Enters HITL review TUI for codes, themes, or interpretations.
Also provides ``enter_review()`` used by ``generate.py`` and
``default.py`` for HITL interleaving.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click
from orchestration.config import (
    common_options,
    resolve_data_path,
    resolve_tags_path,
    validate_paths,
)


@click.command(
    "review",
    help="Enter HITL review TUI for codes, themes, or interpretations. "
    "Default (no --type) reviews all pending artifacts.",
)
@click.option(
    "--type",
    "review_type",
    type=click.Choice(["code", "theme", "interpretation"]),
    help="Artifact type to review (default: all pending)",
)
@common_options
@click.pass_context
def review_cmd(
    ctx: click.Context,
    review_type: Optional[str],
    dry_run: bool,
    verbose: bool,  # noqa: ARG001
    quiet: bool,  # noqa: ARG001
) -> None:
    """Enter HITL review TUI."""
    obj = ctx.obj
    data_path = resolve_data_path(obj)
    tags_path = resolve_tags_path(obj)

    if not validate_paths(data_path, tags_path):
        sys.exit(1)

    if dry_run:
        click.echo("Dry-run: ready to enter review TUI.")
        click.echo(f"  Type: {review_type or 'all'}")
        return

    from persistence.duckdb_connection import DEFAULT_DB_PATH
    from persistence.duckdb_init import init_or_migrate

    con = init_or_migrate()
    try:
        enter_review(con, review_type, DEFAULT_DB_PATH)
    finally:
        con.close()


# ── Public dispatch (used by generate.py and default.py) ────────────────────


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


__all__ = ["enter_review", "review_cmd"]
