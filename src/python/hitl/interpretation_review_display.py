"""Rich rendering for interpretation review HITL CLI.

Provides ``_display_interpretation_panel``, ``_display_evidence_chain``,
and ``_display_interpretation_neighbors`` using ``rich.Panel``,
``rich.Tree``, and ``rich.Table``.
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

console = Console()


def _display_interpretation_panel(interp: dict) -> None:
    """Render a ``rich.Panel`` with interpretation name, narrative, and tag_spans."""
    dj = interp.get("data_json") or {}
    tag_spans = dj.get("tag_spans") or []

    content = Text()
    content.append(f"{interp['name']}\n", style="bold cyan")
    content.append(f"\nNarrative: {interp.get('narrative', '')}\n", style="white")
    content.append(
        f"\nTag spans: {', '.join(tag_spans)}\n",
        style="yellow",
    )

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

    Args:
        themes: List of theme dicts (keys ``id``, ``name``, ``tag``).
        theme_codes_map: Dict mapping theme_id -> list of code dicts.
        code_exemplars_map: Dict mapping code_id -> list of exemplar
            dicts (keys ``id``, ``content``).
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


def _display_interpretation_neighbors(
    neighbors: list[tuple[int, float, str]],
) -> None:
    """Render a ``rich.Table`` of neighbor interpretations with scores."""
    if not neighbors:
        console.print("[dim]No similar interpretations found.[/dim]")
        return

    table = Table(title="Neighbor Interpretations", show_header=True)
    table.add_column("Neighbor ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Similarity", justify="right", style="green")

    for nid, score, name in neighbors:
        table.add_row(str(nid), name, f"{score:.3f}")

    console.print(table)
