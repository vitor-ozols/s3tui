from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.events import MouseScrollDown, MouseScrollUp
from textual.widgets import Button, DataTable, Footer, Header, Input, RichLog, Static

from s3_tui.explorer import ExplorerMixin
from s3_tui.models import PaneState
from s3_tui.preview_panel import PreviewMixin
from s3_tui.s3_service import S3Service


class S3TUI(ExplorerMixin, PreviewMixin, App[None]):
    CSS_PATH = Path(__file__).with_name("styles.tcss")
    TITLE = "S3 Commander"
    SUB_TITLE = "Explorer + details"
    THEMES = ("theme_blue", "theme_emerald", "theme_amber")

    BINDINGS = [
        Binding("enter", "open_selected", "Open", priority=True),
        Binding("backspace", "go_up", "Up"),
        Binding("p", "preview_selected", "Preview"),
        Binding("shift+down", "preview_page_down", "Preview Down"),
        Binding("shift+up", "preview_page_up", "Preview Up"),
        Binding("shift+left", "preview_scroll_left", "Preview Left"),
        Binding("shift+right", "preview_scroll_right", "Preview Right"),
        Binding("shift+d", "download_selected", "Download"),
        Binding("n", "create_directory", "New Dir"),
        Binding("u", "upload_selected", "Upload"),
        Binding("c", "copy_selected", "Copy"),
        Binding("m", "move_selected", "Move"),
        Binding("d", "delete_selected", "Delete"),
        Binding("delete", "delete_selected", show=False),
        Binding("r", "refresh", "Refresh"),
        Binding("t", "toggle_theme", "Theme", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, profile: str | None = None, region: str | None = None) -> None:
        super().__init__()
        self.service = S3Service(profile=profile, region=region)
        self.left = PaneState(table_id="left_table", path_id="left_path")
        self.search_query = ""
        self._last_click_row: int | None = None
        self._last_click_ts = 0.0
        self._theme_index = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="root"):
            with Horizontal(id="panes"):
                with Container(classes="pane"):
                    yield Static("s3://", id="left_path", classes="pane_path")
                    yield Input(placeholder="Search (real-time autocomplete)", id="search_input")
                    yield Static("", id="search_hint", classes="search_hint")
                    yield DataTable(id="left_table", cursor_type="cell")
                with Container(classes="pane"):
                    yield Static("Selected item details", id="right_path", classes="pane_path")
                    yield Static("No item selected.", id="right_info", classes="info_panel")
                    with Horizontal(id="action_buttons"):
                        yield Button("New Dir", id="new_dir_btn", classes="flat-button")
                        yield Button("Upload", id="upload_btn", classes="flat-button")
                        yield Button("Move", id="move_btn", classes="flat-button")
                        yield Button("Delete", id="delete_btn", classes="flat-button")
            with Container(id="preview_wrap"):
                yield Static("Preview", id="preview_title")
                yield DataTable(id="preview_table", cursor_type="cell")
                yield RichLog(id="preview", wrap=False, markup=False, auto_scroll=False)
        yield Footer()

    def on_mount(self) -> None:
        self.dark = True
        self._apply_theme()
        self._init_table(self._table())
        preview_table = self._preview_table()
        if hasattr(preview_table, "show_cursor"):
            preview_table.show_cursor = True
        if hasattr(preview_table, "zebra_stripes"):
            preview_table.zebra_stripes = True
        self._show_log_preview()
        self._refresh_left()
        self._table().focus()
        self._update_right_info(self._selected_entry())
        self._log("Type in the search box to filter and autocomplete in real time.")

    def _apply_theme(self) -> None:
        for theme in self.THEMES:
            self.screen.remove_class(theme)
        self.screen.add_class(self.THEMES[self._theme_index])

    def action_toggle_theme(self) -> None:
        self._theme_index = (self._theme_index + 1) % len(self.THEMES)
        self._apply_theme()
        self._log(f"Theme: {self.THEMES[self._theme_index]}")

    def _path_widget(self) -> Static:
        return self.query_one(f"#{self.left.path_id}", Static)

    def _right_info(self) -> Static:
        return self.query_one("#right_info", Static)

    def _search_hint(self) -> Static:
        return self.query_one("#search_hint", Static)

    def _preview(self) -> RichLog:
        return self.query_one("#preview", RichLog)

    def _preview_table(self) -> DataTable:
        return self.query_one("#preview_table", DataTable)

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        if event.shift:
            self._scroll_preview_horizontal(-4)
            event.stop()

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        if event.shift:
            self._scroll_preview_horizontal(4)
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new_dir_btn":
            self.action_create_directory()
        elif event.button.id == "upload_btn":
            self.action_upload_selected()
        elif event.button.id == "move_btn":
            self.action_move_selected()
        elif event.button.id == "delete_btn":
            self.action_delete_selected()


def main() -> None:
    S3TUI().run()


if __name__ == "__main__":
    main()
