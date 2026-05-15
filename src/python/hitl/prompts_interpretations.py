"""Interpretation review prompts for HITL CLI."""

from pathlib import Path
from typing import Any, Optional

import questionary

from .display import console
from .queries_interpretations import get_interpretation_themes


def prompt_interpretation_action(interp_name: str) -> str:
    """Return the user's chosen action as a lowercase string."""
    action = questionary.select(
        f"Action for interpretation '{interp_name}':",
        choices=[
            "Approve",
            "Edit",
            "Split",
            "Reject",
            "Defer",
        ],
    ).ask()
    return str(action).lower().replace(" ", "_") if action else "defer"


def handle_split_interactive(
    con,
    interp: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Interactive split: select themes, name parts, preview, confirm, execute."""
    themes = get_interpretation_themes(con, interp["id"])
    if len(themes) < 2:
        console.print(
            "[yellow]Split requires at least 2 themes in the interpretation. "
            "Found {}. [/yellow]".format(len(themes))
        )
        return

    choices = []
    for t in themes:
        choices.append(
            questionary.Choice(
                title=f"{t['name']} (#{t['id']}) [tag: {t['tag']}]",
                value=t["id"],
            )
        )

    selected_ids = questionary.checkbox(
        "Select themes for the FIRST new interpretation "
        "(remaining themes will go to the second):",
        choices=choices,
    ).ask()

    if selected_ids is None or len(selected_ids) == 0:
        console.print("[yellow]Split cancelled: no themes selected.[/yellow]")
        return

    first_theme_ids = list(selected_ids)
    second_theme_ids = [t["id"] for t in themes if t["id"] not in first_theme_ids]

    if not second_theme_ids:
        console.print(
            "[yellow]Split cancelled: all themes would go to one "
            "interpretation. Deselect at least one theme.[/yellow]"
        )
        return

    first_name = questionary.text(
        "Name for the first new interpretation:",
        default=f"{interp['name']} (Part 1)",
    ).ask()
    if not first_name:
        console.print("[yellow]Split cancelled.[/yellow]")
        return

    second_name = questionary.text(
        "Name for the second new interpretation:",
        default=f"{interp['name']} (Part 2)",
    ).ask()
    if not second_name:
        console.print("[yellow]Split cancelled.[/yellow]")
        return

    first_narrative = questionary.text(
        "Narrative for the first interpretation:",
        default=interp.get("narrative", ""),
    ).ask()
    if not first_narrative:
        console.print("[yellow]Split cancelled.[/yellow]")
        return

    second_narrative = questionary.text(
        "Narrative for the second interpretation:",
        default=interp.get("narrative", ""),
    ).ask()
    if not second_narrative:
        console.print("[yellow]Split cancelled.[/yellow]")
        return

    first_tag_names = sorted(
        set(t["tag"] for t in themes if t["id"] in first_theme_ids)
    )
    second_tag_names = sorted(
        set(t["tag"] for t in themes if t["id"] in second_theme_ids)
    )

    console.print("\n[bold]Split Preview:[/bold]")
    console.print(
        f"  [cyan]Part 1:[/cyan] '{first_name}' — "
        f"{len(first_theme_ids)} theme(s), tags: {first_tag_names}"
    )
    console.print(
        f"  [cyan]Part 2:[/cyan] '{second_name}' — "
        f"{len(second_theme_ids)} theme(s), tags: {second_tag_names}"
    )
    console.print(f"  [dim]Original '{interp['name']}' will be marked merged.[/dim]\n")

    confirmed = questionary.confirm("Execute split?").ask()
    if not confirmed:
        console.print("[yellow]Split cancelled.[/yellow]")
        return

    from .interpretation_review_split import handle_split_interpretation

    try:
        first_id, second_id = handle_split_interpretation(
            con,
            interp,
            first_theme_ids=first_theme_ids,
            second_theme_ids=second_theme_ids,
            first_name=first_name,
            second_name=second_name,
            first_narrative=first_narrative,
            second_narrative=second_narrative,
            db_path=db_path,
        )
        console.print(
            f"[green]Interpretation '{interp['name']}' split into "
            f"'{first_name}' (#{first_id}) and "
            f"'{second_name}' (#{second_id}).[/green]"
        )
    except ValueError as exc:
        console.print(f"[red]Split failed: {exc}[/red]")
    except Exception:
        console.print("[red]Split failed due to an unexpected error.[/red]")
        raise
