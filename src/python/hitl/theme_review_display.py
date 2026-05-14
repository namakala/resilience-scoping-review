"""Rich rendering for theme review HITL CLI.

Provides ``_display_theme_panel``, ``_display_constituent_codes``,
and ``_display_theme_neighbors`` using ``rich.Panel`` and ``rich.Table``.
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


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


def _display_theme_neighbors(
    neighbors: list[tuple[int, float, str]],
) -> None:
    """Render a ``rich.Table`` of neighbor themes with similarity scores."""
    if not neighbors:
        console.print("[dim]No similar themes found.[/dim]")
        return

    table = Table(title="Similar Themes", show_header=True)
    table.add_column("Neighbor ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Similarity", justify="right", style="green")

    for nid, score, name in neighbors:
        table.add_row(str(nid), name, f"{score:.3f}")

    console.print(table)
