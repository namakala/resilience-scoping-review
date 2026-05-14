"""Interactive CLI for theme review HITL validation — orchestration.

Entry point ``review_themes`` iterates pending themes and dispatches
to display, prompt, and action handler modules.
"""

from pathlib import Path
from typing import Optional

import duckdb

from .theme_review_actions import (
    handle_approve_theme,
    handle_defer_theme,
    handle_edit_theme,
    handle_reject_theme,
)
from .theme_review_display import console
from .theme_review_prompts import (
    _handle_merge_interactive,
    _prompt_edit_codes,
    _prompt_edit_narrative,
    _prompt_theme_action,
)
from .theme_review_queries import (
    _get_constituent_codes,
    _get_pending_themes,
    _get_theme_neighbors,
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
    pending = _get_pending_themes(con, tag=tag)
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
    from .theme_review_display import (
        _display_constituent_codes,
        _display_theme_neighbors,
        _display_theme_panel,
    )

    _display_theme_panel(theme)

    codes = _get_constituent_codes(con, theme["id"])
    _display_constituent_codes(codes)

    neighbors = _get_theme_neighbors(con, theme["id"], k=3)
    _display_theme_neighbors(neighbors)

    action = _prompt_theme_action(theme["name"])

    if action == "approve":
        handle_approve_theme(con, theme, db_path=db_path)
        console.print(f"[green]Theme '{theme['name']}' approved.[/green]")
    elif action == "edit":
        new_narrative = _prompt_edit_narrative(theme.get("narrative", ""))
        if new_narrative is not None:
            new_code_ids = _prompt_edit_codes(con, theme)
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
        _handle_merge_interactive(con, theme, db_path=db_path)
    elif action == "reject":
        handle_reject_theme(con, theme, db_path=db_path)
        console.print(f"[red]Theme '{theme['name']}' rejected.[/red]")
    elif action == "defer":
        handle_defer_theme(con, theme)
        console.print(f"[dim]Theme '{theme['name']}' deferred.[/dim]")
