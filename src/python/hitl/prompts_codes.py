"""Code review prompts for HITL CLI."""

import difflib

from persistence.loaders import load_exemplars
from rich.panel import Panel

from .display import console


def prompt_code_action(code_name: str) -> str:
    """Return the user's chosen action as a lowercase string."""
    import questionary

    action = questionary.select(
        f"Action for code '{code_name}':",
        choices=[
            "Approve",
            "Edit",
            "Merge",
            "Reject",
            "Defer",
            "More context",
        ],
    ).ask()
    return str(action).lower().replace(" ", "_") if action else "defer"


def handle_merge_interactive_code(con, source_code, db_path=None):
    """Interactive merge: select target, show diff, confirm, execute."""
    import questionary

    from .code_review_merge import handle_merge

    source_id = source_code["id"]
    candidates = con.execute(
        "SELECT id, name, definition FROM nodes "
        "WHERE type = 'code' AND status = 'draft' AND id != ? "
        "ORDER BY name",
        [source_id],
    ).fetchall()

    if not candidates:
        console.print("[yellow]No other draft codes available for merge.[/yellow]")
        return

    choices = [f"{c[1]} (#{c[0]})" for c in candidates]
    selected = questionary.select(
        "Select code to merge into:",
        choices=choices,
    ).ask()
    if selected is None:
        return

    choice_index = choices.index(selected)
    target_id = candidates[choice_index][0]
    target_def = candidates[choice_index][2]

    diff = difflib.unified_diff(
        source_code.get("definition", "").splitlines(keepends=True),
        target_def.splitlines(keepends=True),
        fromfile=f"Source: {source_code['name']}",
        tofile=f"Target: {candidates[choice_index][1]}",
    )
    diff_text = "".join(diff)
    console.print("[bold]Definition diff:[/bold]")
    console.print(diff_text if diff_text else "[dim](identical definitions)[/dim]")

    confirmed = questionary.confirm("Execute merge?").ask()
    if confirmed:
        handle_merge(con, source_code, target_id, db_path=db_path)
        console.print(
            f"[green]Code '{source_code['name']}' merged into "
            f"'{candidates[choice_index][1]}'.[/green]"
        )


def show_more_context(con, code):
    """Show full exemplar content in a panel, then return for re-prompt."""
    dj = code.get("data_json", {})
    exemplar_ids = dj.get("exemplar_ids", [])

    if not exemplar_ids:
        console.print("[yellow]No exemplars linked to this code.[/yellow]")
        return

    try:
        lf = load_exemplars()
        for eid in exemplar_ids:
            try:
                numeric_id = int(eid)
            except (ValueError, TypeError):
                continue
            row = (
                lf.filter(__import__("polars").col("id") == numeric_id)
                .select(["id", "content"])
                .collect()
                .rows()
            )
            if row:
                content_panel = Panel(
                    str(row[0][1]),
                    title=f"Full Exemplar #{eid}",
                    border_style="green",
                )
                console.print(content_panel)
            else:
                console.print(f"[dim]Exemplar #{eid} not found in parquet.[/dim]")
    except FileNotFoundError:
        console.print("[yellow]Exemplars parquet not found.[/yellow]")
