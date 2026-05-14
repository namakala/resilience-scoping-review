"""Interactive CLI for code review HITL validation — orchestration.

Entry point ``review_codes`` iterates pending codes and dispatches
to display, prompt, and action handler modules.
"""

from pathlib import Path
from typing import Optional

import duckdb

from .code_review_actions import (
    handle_approve,
    handle_defer,
    handle_edit,
    handle_reject,
)
from .prompts import _handle_merge_interactive_code as _handle_merge_interactive
from .prompts import _prompt_code_action as _prompt_action
from .prompts import _show_more_context
from .queries import _get_neighbors_code as _get_neighbors
from .queries import _get_pending_codes
from .shared import console

__all__ = ["review_codes"]


def review_codes(
    con: duckdb.DuckDBPyConnection,
    db_path: Optional[Path] = None,
) -> None:
    """Run interactive code review for all pending (draft) codes.

    For each pending code, displays:
    - Code name, definition, supporting quote (truncated)
    - Semantic neighbor codes with similarity scores
    - Action prompt: Approve, Edit, Merge, Reject, Defer, More context

    Args:
        con: Active DuckDB connection.
        db_path: Path to DuckDB file (needed by graph sync operations).
    """
    pending = _get_pending_codes(con)
    if not pending:
        console.print("[bold green]No pending codes to review.[/bold green]")
        return

    console.print(f"[bold]Reviewing {len(pending)} code(s)...[/bold]\n")

    for code in pending:
        try:
            _review_single_code(con, code, db_path)
        except KeyboardInterrupt:
            console.print(
                "\n[yellow]Review session interrupted. Progress saved.[/yellow]"
            )
            return


def _review_single_code(
    con: duckdb.DuckDBPyConnection,
    code: dict,
    db_path: Optional[Path] = None,
) -> None:
    """Display, prompt, and dispatch action for a single code."""
    from .display import _display_code_panel, _display_neighbors_table

    _display_code_panel(code)

    neighbors = _get_neighbors(con, code["id"])
    _display_neighbors_table("Semantic Neighbors", neighbors)

    action = _prompt_action(code["name"])

    if action == "approve":
        handle_approve(con, code, db_path=db_path)
        console.print(f"[green]Code '{code['name']}' approved.[/green]")
    elif action == "edit":
        import questionary

        new_def = questionary.text(
            "Edit definition",
            default=code.get("definition", ""),
            validate=lambda v: len(v.strip()) > 0 or "Definition cannot be empty",
        ).ask()
        if new_def is not None:
            handle_edit(con, code, db_path=db_path, new_definition=new_def)
            console.print(f"[green]Code '{code['name']}' updated.[/green]")
    elif action == "merge":
        _handle_merge_interactive(con, code, db_path=db_path)
    elif action == "reject":
        handle_reject(con, code, db_path=db_path)
        console.print(f"[red]Code '{code['name']}' rejected.[/red]")
    elif action == "defer":
        handle_defer(con, code, db_path=db_path)
        console.print(f"[dim]Code '{code['name']}' deferred.[/dim]")
    elif action == "more_context":
        _show_more_context(con, code)
        _review_single_code(con, code, db_path)
