from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class DeleteConfirmScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    DeleteConfirmScreen {
        align: center middle;
    }
    """

    BINDINGS = [
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel", "No"),
        Binding("left", "focus_yes", show=False, priority=True),
        Binding("right", "focus_no", show=False, priority=True),
        Binding("up", "focus_yes", show=False, priority=True),
        Binding("down", "focus_no", show=False, priority=True),
        Binding("enter", "submit_focused", show=False, priority=True),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, target_label: str, target_kind: str) -> None:
        super().__init__()
        self.target_label = target_label
        self.target_kind = target_kind

    def compose(self) -> ComposeResult:
        with Container(id="confirm_modal"):
            yield Static("Confirm delete", id="confirm_modal_title")
            yield Static(
                f"Delete {self.target_kind}?\n{self.target_label}",
                id="confirm_modal_body",
            )
            yield Static("Press Y to confirm or N to cancel.", id="confirm_modal_hint")
            with Horizontal(id="confirm_modal_actions"):
                yield Button("Yes", id="confirm_yes_btn", classes="flat-button confirm-danger")
                yield Button("No", id="confirm_no_btn", classes="flat-button confirm-neutral")

    def on_mount(self) -> None:
        self.query_one("#confirm_yes_btn", Button).focus()

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_focus_yes(self) -> None:
        self.query_one("#confirm_yes_btn", Button).focus()

    def action_focus_no(self) -> None:
        self.query_one("#confirm_no_btn", Button).focus()

    def action_submit_focused(self) -> None:
        focused = self.focused
        if isinstance(focused, Button) and focused.id == "confirm_no_btn":
            self.action_cancel()
            return
        self.action_confirm()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm_yes_btn":
            self.action_confirm()
        elif event.button.id == "confirm_no_btn":
            self.action_cancel()

    def on_key(self, event: Key) -> None:
        if event.key == "y":
            self.action_confirm()
            event.stop()
        elif event.key == "n":
            self.action_cancel()
            event.stop()
