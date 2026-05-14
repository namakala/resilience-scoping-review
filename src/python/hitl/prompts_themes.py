"""Theme review prompts for HITL CLI."""

from pathlib import Path
from typing import Any, Optional

import questionary

from .display import _display_constituent_codes, console
from .queries_themes import (
    get_available_codes_for_tag,
    get_constituent_codes,
    get_other_draft_themes,
)


def prompt_theme_action(theme_name: str) -> str:
    """Return the user's chosen action as a lowercase string."""
    action = questionary.select(
        f"Action for theme '{theme_name}':",
        choices=[
            "Approve",
            "Edit",
            "Merge",
            "Reject",
            "Defer",
        ],
    ).ask()
    return str(action).lower().replace(" ", "_") if action else "defer"


def prompt_edit_codes(con, theme: dict) -> Optional[list[int]]:
    """Multi-select codes for the theme, returning updated code ID list.

    Shows all available codes for the theme's tag alongside their
    status.  Pre-selects codes currently in the theme.  Returns
    ``None`` if cancelled.
    """
    available = get_available_codes_for_tag(con, theme["tag"])
    if not available:
        console.print("[yellow]No codes available for this tag.[/yellow]")
        return None

    current_code_ids = set(theme.get("data_json", {}).get("code_ids", []))

    choices = []
    for c in available:
        preselected = c["id"] in current_code_ids
        choices.append(
            questionary.Choice(
                title=f"{c['name']} (#{c['id']}) [{c['status']}]",
                value=c["id"],
                checked=preselected,
            )
        )

    selected = questionary.checkbox(
        "Select codes for this theme:",
        choices=choices,
    ).ask()

    if selected is None:
        return None
    return list(selected)


def handle_merge_interactive_theme(
    con,
    source_theme: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Interactive merge: select target, show preview, confirm, execute."""
    from .theme_review_merge import handle_merge_themes

    source_id = source_theme["id"]
    tag = source_theme.get("tag", "")

    candidates = get_other_draft_themes(con, source_id, tag)
    if not candidates:
        console.print(
            "[yellow]No other draft themes available for merge in this tag.[/yellow]"
        )
        return

    choices = [f"{c['name']} (#{c['id']})" for c in candidates]
    selected = questionary.select(
        "Select theme to merge into:",
        choices=choices,
    ).ask()
    if selected is None:
        return

    choice_index = choices.index(selected)
    target = candidates[choice_index]

    source_codes = get_constituent_codes(con, source_id)
    target_codes = get_constituent_codes(con, target["id"])

    console.print("\n[bold]Merge Preview:[/bold]")
    _display_constituent_codes(source_codes, title=f"Source: {source_theme['name']}")
    _display_constituent_codes(target_codes, title=f"Target: {target['name']}")

    source_code_ids = set(source_theme.get("data_json", {}).get("code_ids", []))
    target_code_ids = set(target.get("code_ids", []))
    combined = source_code_ids | target_code_ids

    console.print(
        f"\n[dim]Source has {len(source_code_ids)} code(s), "
        f"Target has {len(target_code_ids)} code(s), "
        f"combined would have {len(combined)} unique code(s).[/dim]"
    )

    confirmed = questionary.confirm("Execute merge?").ask()
    if confirmed:
        handle_merge_themes(con, source_theme, target["id"], db_path=db_path)
        console.print(
            f"[green]Theme '{source_theme['name']}' merged into "
            f"'{target['name']}'.[/green]"
        )
