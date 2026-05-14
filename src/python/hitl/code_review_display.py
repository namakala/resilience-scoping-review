"""Rich rendering for code review HITL CLI.

Provides ``_display_code_panel`` and ``_display_neighbors`` using
``rich.Panel`` and ``rich.Table``.
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

TRUNCATE_LENGTH = 100


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


def _display_neighbors(
    neighbors: list[tuple[int, float, str]],
) -> None:
    """Render a ``rich.Table`` of neighbor codes with similarity scores."""
    if not neighbors:
        console.print("[dim]No similar codes found.[/dim]")
        return

    table = Table(title="Semantic Neighbors", show_header=True)
    table.add_column("Neighbor ID", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Similarity", justify="right", style="green")

    for nid, score, name in neighbors:
        table.add_row(str(nid), name, f"{score:.3f}")

    console.print(table)
