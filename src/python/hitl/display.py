"""Rich rendering for HITL review CLI.

Consolidated from per-entity display modules.  Entity-specific panel
rendering functions are prefixed by their entity type.  The ``console``
singleton is imported from ``.shared``.
"""

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .shared import console

TRUNCATE_LENGTH = 100


# ── Neighbor table helper (shared across entity types) ──────────────


def _display_neighbors_table(
    title: str,
    neighbors: list[tuple[int, float, str]],
) -> None:
    """Render a ``rich.Table`` of neighbor entities with similarity scores."""
    if not neighbors:
        console.print("[dim]No similar entities found.[/dim]")
        return

    table = Table(title=title, show_header=True)
    table.add_column("Neighbor ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Similarity", justify="right", style="green")

    for nid, score, name in neighbors:
        table.add_row(str(nid), name, f"{score:.3f}")

    console.print(table)


# ── Code review display ─────────────────────────────────────────────


def _display_code_panel(code: dict) -> None:
    """Render a ``rich.Panel`` with code name, definition, quote, and tag."""
    dj = code.get("data_json", {})
    supporting_quotes: dict = dj.get("supporting_quotes", {})
    exemplar_ids: list = dj.get("exemplar_ids", [])

    primary_eid = exemplar_ids[0] if exemplar_ids else "?"
    quote_text = supporting_quotes.get(primary_eid, "")
    truncated = (
        quote_text[:TRUNCATE_LENGTH] + "..."
        if len(quote_text) > TRUNCATE_LENGTH
        else quote_text
    )

    content = Text()
    content.append(f"{code['name']}\n", style="bold cyan")
    content.append(f"\nDefinition: {code['definition']}\n", style="white")
    content.append(f"\nTag: {code['tag']}\n", style="yellow")
    content.append(f'\nSupporting quote: "{truncated}"\n', style="italic green")

    panel = Panel(content, title=f"Code #{code['id']}", border_style="blue")
    console.print(panel)


# ── Theme review display ────────────────────────────────────────────


def _display_theme_panel(theme: dict) -> None:
    """Render a ``rich.Panel`` with theme name, narrative, and tag."""
    content = Text()
    content.append(f"{theme['name']}\n", style="bold cyan")
    content.append(f"\nNarrative: {theme.get('narrative', '')}\n", style="white")
    content.append(f"\nTag: {theme['tag']}\n", style="yellow")

    panel = Panel(content, title=f"Theme #{theme['id']}", border_style="blue")
    console.print(panel)


def _display_constituent_codes(
    codes: list[dict],
    title: str = "Constituent Codes",
) -> None:
    """Render a ``rich.Table`` of codes with ID, name, status, and exemplar count."""
    if not codes:
        console.print("[dim]No codes associated with this theme.[/dim]")
        return

    table = Table(title=title, show_header=True)
    table.add_column("Code ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Status", style="yellow")
    table.add_column("Exemplars", justify="right", style="green")

    for c in codes:
        table.add_row(
            str(c["id"]),
            c.get("name", ""),
            c.get("status", ""),
            str(c.get("exemplar_count", 0)),
        )

    console.print(table)


# ── Interpretation review display ───────────────────────────────────


def _display_interpretation_panel(interp: dict) -> None:
    """Render a ``rich.Panel`` with name, narrative, tag_spans, and status."""
    dj = interp.get("data_json") or {}
    tag_spans = dj.get("tag_spans") or []
    status = interp.get("status", "draft")
    status_style = "green" if status == "approved" else "yellow"

    content = Text()
    content.append(f"{interp['name']}\n", style="bold cyan")
    content.append(f"\nNarrative: {interp.get('narrative', '')}\n", style="white")
    content.append(
        f"\nTag spans: {', '.join(tag_spans)}\n",
        style="yellow",
    )
    content.append(f"\nStatus: {status}\n", style=status_style)

    panel = Panel(
        content,
        title=f"Interpretation #{interp['id']}",
        border_style="blue",
    )
    console.print(panel)


def _display_evidence_chain(
    themes: list[dict],
    theme_codes_map: dict[int, list[dict]],
    code_exemplars_map: dict[int, list[dict]],
) -> None:
    """Render a hierarchical evidence chain using ``rich.tree.Tree``.

    Structure::

        Interpretation
        └── spans → Theme "T1" [tag: Problem.Cause]
            └── composed-of → Code "C1"
                └── contains → Exemplar #42: "quote excerpt..."
    """
    tree = Tree("[bold]Evidence Chain[/bold]")

    for theme in themes:
        theme_label = (
            f"[cyan]spans →[/cyan] [white]{theme['name']}[/white] "
            f"[yellow][tag: {theme['tag']}][/yellow]"
        )
        theme_branch = tree.add(theme_label)

        codes = theme_codes_map.get(theme["id"], [])
        for code in codes:
            code_label = f"[cyan]composed-of →[/cyan] [white]{code['name']}[/white]"
            code_branch = theme_branch.add(code_label)

            exemplars = code_exemplars_map.get(code["id"], [])
            for ex in exemplars:
                ex_label = (
                    f"[cyan]contains →[/cyan] "
                    f"[green]Exemplar #{ex['id']}:[/green] "
                    f'[dim]"{ex["content"]}"[/dim]'
                )
                code_branch.add(ex_label)

            if not exemplars:
                code_branch.add("[dim]No exemplars linked.[/dim]")

    console.print(tree)
