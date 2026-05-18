"""Modal screen for selecting which statuses to display in the entity
browser.

Provides a checklist of all known status values.  The user can tick
or un-tick any combination.  On "Apply" the modal dismisses with
the set of selected statuses.  On "Cancel" or Escape it dismisses
with ``None``.
"""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, SelectionList, Static

STATUS_LABELS: dict[str, str] = {
    "draft": "Draft",
    "pending": "Pending",
    "approved": "Approved",
    "rejected": "Rejected",
    "merged": "Merged",
    "superseded": "Superseded",
}

ALL_STATUSES = list(STATUS_LABELS.keys())

DEFAULT_FILTER: set[str] = {"draft", "pending", "approved"}


class StatusFilterModal(ModalScreen[Optional[set[str]]]):
    """Modal for selecting which statuses to display.

    Returns the set of selected status strings, or ``None`` if the
    user cancelled.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, current_filter: set[str]) -> None:
        super().__init__()
        self._current_filter = current_filter or DEFAULT_FILTER

    def compose(self) -> ComposeResult:
        with Vertical(id="filter-form"):
            yield Static("[bold]Filter by Status[/bold]", id="filter-title")
            yield Label("Show entities with these statuses:")
            yield SelectionList[str](
                id="status-selection",
                *[
                    (label, status, status in self._current_filter)
                    for status, label in STATUS_LABELS.items()
                ],
            )
            with Horizontal(classes="modal-buttons"):
                yield Button("Apply", variant="primary", id="filter-apply")
                yield Button("Cancel", variant="default", id="filter-cancel")

    CSS = """
    StatusFilterModal {
        align: center middle;
    }
    #filter-form {
        width: 50;
        max-width: 80vw;
    }
    #filter-form > Static, #filter-form > Label,
    #filter-form > SelectionList, #filter-form > Horizontal {
        width: 100%;
    }
    #filter-title {
        text-align: center;
        padding: 1 0;
    }
    #status-selection {
        height: auto;
        max-height: 20;
        margin: 1 0;
        border: solid $primary;
    }
    .modal-buttons {
        align-horizontal: center;
        height: 3;
    }
    .modal-buttons Button {
        margin: 0 1;
    }
    """

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "filter-apply":
            selection_list = self.query_one("#status-selection", SelectionList[str])
            selected: list[str] = selection_list.selected
            self.dismiss(set(selected))
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = [
    "ALL_STATUSES",
    "DEFAULT_FILTER",
    "STATUS_LABELS",
    "StatusFilterModal",
]
