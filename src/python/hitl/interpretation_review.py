"""Interactive CLI for interpretation review HITL validation — orchestration.

Entry point ``review_interpretations`` iterates pending interpretations
and dispatches to display, prompt, and action handler modules.
"""

from pathlib import Path
from typing import Optional

import duckdb

from .interpretation_review_actions import (
    handle_approve_interpretation,
    handle_defer_interpretation,
    handle_edit_interpretation,
    handle_reject_interpretation,
)
from .prompts import prompt_edit_text as prompt_edit_narrative
from .prompts_interpretations import (
    handle_split_interactive,
    prompt_interpretation_action,
)
from .queries_codes import get_code_exemplars
from .queries_interpretations import get_interpretation_themes
from .queries_interpretations import (
    get_neighbors_interpretation as get_interpretation_neighbors,
)
from .queries_interpretations import get_pending_interpretations
from .queries_themes import get_theme_codes
from .shared import console

__all__ = ["review_interpretations"]


def review_interpretations(
    con: duckdb.DuckDBPyConnection,
    tag: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Run interactive interpretation review for pending (draft) interpretations.

    For each pending interpretation, displays:
    - Interpretation name, narrative, and tag spans
    - Evidence chain: themes → codes → exemplar excerpts
    - Neighbor interpretations (up to 3)
    - Action prompt: Approve, Edit, Split, Reject, Defer

    Args:
        con: Active DuckDB connection.
        tag: Optional ontology tag to filter interpretations. ``None``
            reviews all draft interpretations.
        db_path: Path to DuckDB file (needed by graph sync operations).
    """
    pending = get_pending_interpretations(con, tag=tag)
    if not pending:
        label = f" for tag '{tag}'" if tag else ""
        console.print(
            f"[bold green]No pending interpretations to review{label}.[/bold green]"
        )
        return

    console.print(f"[bold]Reviewing {len(pending)} interpretation(s)...[/bold]\n")

    for interp in pending:
        try:
            _review_single_interpretation(con, interp, db_path)
        except KeyboardInterrupt:
            console.print(
                "\n[yellow]Review session interrupted. Progress saved.[/yellow]"
            )
            return


def _review_single_interpretation(
    con: duckdb.DuckDBPyConnection,
    interp: dict,
    db_path: Optional[Path] = None,
) -> None:
    """Display, prompt, and dispatch action for a single interpretation."""
    from .display import (
        _display_evidence_chain,
        _display_interpretation_panel,
        _display_neighbors_table,
    )

    _display_interpretation_panel(interp)

    # Build and display evidence chain
    themes = get_interpretation_themes(con, interp["id"])
    theme_codes_map: dict[int, list[dict]] = {}
    code_exemplars_map: dict[int, list[dict]] = {}

    for theme in themes:
        codes = get_theme_codes(con, theme["id"])
        theme_codes_map[theme["id"]] = codes
        for code in codes:
            code_exemplars_map[code["id"]] = get_code_exemplars(con, code["id"])

    _display_evidence_chain(themes, theme_codes_map, code_exemplars_map)

    # Show neighbor interpretations
    neighbors = get_interpretation_neighbors(con, interp["id"], k=3)
    _display_neighbors_table("Neighbor Interpretations", neighbors)

    # Prompt for action
    action = prompt_interpretation_action(interp["name"])

    if action == "approve":
        handle_approve_interpretation(con, interp, db_path=db_path)
        console.print(f"[green]Interpretation '{interp['name']}' approved.[/green]")
    elif action == "edit":
        new_narrative = prompt_edit_narrative(interp.get("narrative", ""))
        if new_narrative is not None:
            handle_edit_interpretation(
                con,
                interp,
                db_path=db_path,
                new_narrative=new_narrative,
            )
            console.print(f"[green]Interpretation '{interp['name']}' updated.[/green]")
        else:
            console.print("[yellow]Edit cancelled.[/yellow]")
    elif action == "split":
        handle_split_interactive(con, interp, db_path=db_path)
    elif action == "reject":
        handle_reject_interpretation(con, interp, db_path=db_path)
        console.print(f"[red]Interpretation '{interp['name']}' rejected.[/red]")
    elif action == "defer":
        handle_defer_interpretation(con, interp)
        console.print(f"[dim]Interpretation '{interp['name']}' deferred.[/dim]")
