"""Interactive CLI for theme review HITL validation — orchestration.

Entry point ``review_themes`` iterates pending themes and dispatches
to display, prompt, and action handler modules.
"""

from pathlib import Path
from typing import Optional

import duckdb

from .prompts import prompt_edit_text as prompt_edit_narrative
from .prompts_themes import handle_merge_interactive_theme as handle_merge_interactive
from .prompts_themes import prompt_edit_codes, prompt_theme_action
from .queries_themes import get_constituent_codes
from .queries_themes import get_neighbors_theme as get_theme_neighbors
from .queries_themes import get_pending_themes
from .shared import console
from .theme_review_actions import (
    handle_approve_theme,
    handle_defer_theme,
    handle_edit_theme,
    handle_reject_theme,
)

__all__ = ["review_themes"]


def review_themes(
    con: duckdb.DuckDBPyConnection,
    tag: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Run interactive theme review for pending (draft) themes.

    For each pending theme, displays:
    - Theme name, narrative, and tag
    - Constituent codes with exemplar counts
    - Similar themes from neighbor discovery (up to 3)
    - Action prompt: Approve, Edit, Merge, Reject, Defer

    Args:
        con: Active DuckDB connection.
        tag: Optional ontology tag to filter themes.  ``None`` reviews
            all draft themes.
        db_path: Path to DuckDB file (needed by graph sync operations).
    """
    pending = get_pending_themes(con, tag=tag)
    if not pending:
        label = f" for tag '{tag}'" if tag else ""
        console.print(f"[bold green]No pending themes to review{label}.[/bold green]")
        return

    console.print(f"[bold]Reviewing {len(pending)} theme(s)...[/bold]\n")

    for theme in pending:
        try:
            _review_single_theme(con, theme, db_path)
        except KeyboardInterrupt:
            console.print(
                "\n[yellow]Review session interrupted. Progress saved.[/yellow]"
            )
            return


def _review_single_theme(
    con: duckdb.DuckDBPyConnection,
    theme: dict,
    db_path: Optional[Path] = None,
) -> None:
    """Display, prompt, and dispatch action for a single theme."""
    from .display import (
        _display_constituent_codes,
        _display_neighbors_table,
        _display_theme_panel,
    )

    _display_theme_panel(theme)

    codes = get_constituent_codes(con, theme["id"])
    _display_constituent_codes(codes)

    neighbors = get_theme_neighbors(con, theme["id"], k=3)
    _display_neighbors_table("Similar Themes", neighbors)

    action = prompt_theme_action(theme["name"])

    if action == "approve":
        handle_approve_theme(con, theme, db_path=db_path)
        console.print(f"[green]Theme '{theme['name']}' approved.[/green]")
    elif action == "edit":
        new_narrative = prompt_edit_narrative(theme.get("narrative", ""))
        if new_narrative is not None:
            new_code_ids = prompt_edit_codes(con, theme)
            if new_code_ids is not None:
                handle_edit_theme(
                    con,
                    theme,
                    db_path=db_path,
                    new_narrative=new_narrative,
                    new_code_ids=new_code_ids,
                )
                console.print(f"[green]Theme '{theme['name']}' updated.[/green]")
            else:
                console.print("[yellow]Edit cancelled.[/yellow]")
        else:
            console.print("[yellow]Edit cancelled.[/yellow]")
    elif action == "merge":
        handle_merge_interactive(con, theme, db_path=db_path)
    elif action == "reject":
        handle_reject_theme(con, theme, db_path=db_path)
        console.print(f"[red]Theme '{theme['name']}' rejected.[/red]")
    elif action == "defer":
        handle_defer_theme(con, theme)
        console.print(f"[dim]Theme '{theme['name']}' deferred.[/dim]")
