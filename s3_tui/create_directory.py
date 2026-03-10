from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


class CreateDirectoryScreen(ModalScreen[str | None]):
    DEFAULT_CSS = """
    CreateDirectoryScreen {
        align: center middle;
    }
    """

    BINDINGS = [
        Binding("enter", "submit_focused", show=False, priority=True),
        Binding("escape", "cancel", "Cancel"),
        Binding("left", "focus_create", show=False, priority=True),
        Binding("right", "focus_cancel", show=False, priority=True),
        Binding("up", "focus_input", show=False, priority=True),
        Binding("down", "focus_create", show=False, priority=True),
    ]

    def __init__(self, current_path: str) -> None:
        super().__init__()
        self.current_path = current_path

    def compose(self) -> ComposeResult:
        with Container(id="create_dir_modal"):
            yield Static("Create directory", id="create_dir_modal_title")
            yield Static(self.current_path, id="create_dir_modal_path")
            yield Input(placeholder="Directory name", id="create_dir_input")
            yield Static("Type the name and press Enter, or use the buttons.", id="create_dir_modal_hint")
            with Horizontal(id="create_dir_modal_actions"):
                yield Button("Create", id="create_dir_create_btn", classes="flat-button confirm-create")
                yield Button("Cancel", id="create_dir_cancel_btn", classes="flat-button confirm-neutral")

    def on_mount(self) -> None:
        self.query_one("#create_dir_input", Input).focus()

    def action_focus_input(self) -> None:
        self.query_one("#create_dir_input", Input).focus()

    def action_focus_create(self) -> None:
        self.query_one("#create_dir_create_btn", Button).focus()

    def action_focus_cancel(self) -> None:
        self.query_one("#create_dir_cancel_btn", Button).focus()

    def action_submit_focused(self) -> None:
        focused = self.focused
        if isinstance(focused, Button):
            if focused.id == "create_dir_cancel_btn":
                self.action_cancel()
                return
            self.action_submit()
            return
        self.action_submit()

    def action_submit(self) -> None:
        value = self.query_one("#create_dir_input", Input).value.strip()
        self.dismiss(value or None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create_dir_create_btn":
            self.action_submit()
        elif event.button.id == "create_dir_cancel_btn":
            self.action_cancel()
