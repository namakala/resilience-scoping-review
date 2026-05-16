"""Default handler — invoked when no subcommand is given.

Checks for existing codes, prompts to generate if none exist,
otherwise enters review TUI.
"""

from __future__ import annotations

import click


def handle_default(obj: dict) -> None:
    """Default entry when no subcommand is given.

    Enters review TUI. If no reviewable artifacts exist, prompts to
    generate codes first.
    """
    click.echo("Connecting to session...")

    from persistence.duckdb_init import init_or_migrate

    con = init_or_migrate()
    try:
        _check_database_nodes(con, obj)
    finally:
        con.close()


# ── Internal dispatchers ────────────────────────────────────────────────────


def _check_database_nodes(con, obj: dict) -> None:
    """Check for existing reviewable nodes and dispatch accordingly."""
    if _has_nodes_of_type(con, "code"):
        click.echo("Reviewable artifacts found. Entering review TUI...")
        from orchestration.review import enter_review
        from persistence.duckdb_connection import DEFAULT_DB_PATH

        enter_review(con, None, DEFAULT_DB_PATH)
        return

    click.echo("No codes found.")
    if click.confirm("Generate codes first?", default=True):
        con.close()
        _run_and_review(obj)


def _run_and_review(obj: dict) -> None:
    """Generate codes then enter review TUI."""
    from orchestration.run import run_sequence

    click.echo("Running code generation...")
    run_sequence(("code",), ctx_obj=obj)


def _has_nodes_of_type(con, node_type: str) -> bool:
    """Check whether the DuckDB has any nodes of the given type."""
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM nodes WHERE type = ?",
            [node_type],
        ).fetchone()
        return row is not None and row[0] > 0
    except Exception:
        return False


__all__ = ["handle_default"]
