"""Interactive prompts for HITL review CLI.

Consolidated from per-entity prompt modules.  Shared helpers are
defined here; entity-specific action prompts and interactive flows
are prefixed by entity type.
"""

import difflib
from pathlib import Path
from typing import Any, Optional

from persistence.loaders import load_exemplars
from rich.panel import Panel

from .display import _display_constituent_codes, console
from .queries import (
    _get_available_codes_for_tag,
    _get_constituent_codes,
    _get_interpretation_themes,
    _get_other_draft_themes,
)

# ── Shared prompt helpers ───────────────────────────────────────────


def _prompt_edit_text(label: str, default: str = "") -> Optional[str]:
    """Prompt the user to edit a text value.

    Returns the updated text, or ``None`` if cancelled.
    """
    import questionary

    result = questionary.text(
        label,
        default=default,
        validate=lambda v: len(v.strip()) > 0 or f"{label} cannot be empty",
    ).ask()
    return result  # type: ignore[no-any-return]


# ── Code review prompts ─────────────────────────────────────────────


def _prompt_code_action(code_name: str) -> str:
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


def _handle_merge_interactive_code(con, source_code, db_path=None):
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


def _show_more_context(con, code):
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


# ── Theme review prompts ────────────────────────────────────────────


def _prompt_theme_action(theme_name: str) -> str:
    """Return the user's chosen action as a lowercase string."""
    import questionary

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


def _prompt_edit_codes(con, theme: dict) -> Optional[list[int]]:
    """Multi-select codes for the theme, returning updated code ID list.

    Shows all available codes for the theme's tag alongside their
    status.  Pre-selects codes currently in the theme.  Returns
    ``None`` if cancelled.
    """
    import questionary

    available = _get_available_codes_for_tag(con, theme["tag"])
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


def _handle_merge_interactive_theme(
    con,
    source_theme: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Interactive merge: select target, show preview, confirm, execute."""
    import questionary

    from .theme_review_merge import handle_merge_themes

    source_id = source_theme["id"]
    tag = source_theme.get("tag", "")

    candidates = _get_other_draft_themes(con, source_id, tag)
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

    # Preview: show code lists side by side
    source_codes = _get_constituent_codes(con, source_id)
    target_codes = _get_constituent_codes(con, target["id"])

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


# ── Interpretation review prompts ───────────────────────────────────


def _prompt_interpretation_action(interp_name: str) -> str:
    """Return the user's chosen action as a lowercase string."""
    import questionary

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


def _handle_split_interactive(
    con,
    interp: dict[str, Any],
    db_path: Optional[Path] = None,
) -> None:
    """Interactive split: select themes, name parts, preview, confirm, execute."""
    import questionary

    themes = _get_interpretation_themes(con, interp["id"])
    if len(themes) < 2:
        console.print(
            "[yellow]Split requires at least 2 themes in the interpretation. "
            "Found {}. [/yellow]".format(len(themes))
        )
        return

    # Theme selection for first new interpretation
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

    # Prompt for names and narratives
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

    # Preview
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
