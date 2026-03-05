from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from time import monotonic

from botocore.exceptions import BotoCoreError, ClientError
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.events import Click, Key, MouseScrollDown, MouseScrollUp
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Input, RichLog, Static

from s3_tui.preview import build_preview, build_table_preview, is_image_file
from s3_tui.s3_service import S3Entry, S3Service

try:
    from PIL import Image as PILImage
    from PIL import UnidentifiedImageError
except ImportError:  # pragma: no cover - optional dependency fallback
    PILImage = None

    class UnidentifiedImageError(Exception):
        pass

try:
    from rich.image import Image as RichImage
except ImportError:  # pragma: no cover - rich image API unavailable
    RichImage = None


@dataclass(slots=True)
class PaneState:
    table_id: str
    path_id: str
    mode: str = "buckets"
    bucket: str | None = None
    prefix: str = ""
    entries: list[S3Entry] = field(default_factory=list)
    all_entries: list[S3Entry] = field(default_factory=list)

    @property
    def path(self) -> str:
        if self.mode == "buckets":
            return "s3://"
        return f"s3://{self.bucket}/{self.prefix}"


@dataclass(slots=True)
class LocalFsEntry:
    path: Path
    name: str
    kind: str
    size: int = 0
    modified: datetime | None = None


class UploadFsTable(DataTable):
    """DataTable que sobrescreve action_select_cursor para controlar o Enter."""

    BINDINGS = [
        Binding("u", "upload_selected", show=False, priority=True),
        Binding("backspace", "go_parent", show=False, priority=True),
    ]

    def action_select_cursor(self) -> None:
        # Sobrescreve o handler padrão do Enter do DataTable.
        # Em vez de emitir CellSelected/RowSelected, chama diretamente
        # action_open_or_select na screen.
        callback = getattr(self.screen, "action_open_or_select", None)
        if callable(callback):
            callback()

    def action_upload_selected(self) -> None:
        callback = getattr(self.screen, "action_upload_selected", None)
        if callable(callback):
            callback()

    def action_go_parent(self) -> None:
        callback = getattr(self.screen, "action_go_parent", None)
        if callable(callback):
            callback()


class UploadPickerScreen(ModalScreen[Path | None]):
    BINDINGS = [
        Binding("u", "upload_selected", "Upload"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, start_dir: Path | None = None) -> None:
        super().__init__()
        self.current_dir = (start_dir or Path.home()).expanduser().resolve()
        self.entries: list[LocalFsEntry] = []
        self.status_message = ""
        self._last_mouse_click_row: int | None = None
        self._last_mouse_click_ts: float = 0.0

    def compose(self) -> ComposeResult:
        with Container(id="upload_modal"):
            yield Static("Upload (file or folder)", id="upload_modal_title")
            yield Static("", id="upload_current_path")
            yield Static("", id="upload_status")
            yield UploadFsTable(id="upload_fs_table", cursor_type="cell")
            with Horizontal(id="upload_modal_actions"):
                yield Button("Upload selected", id="upload_select_btn", variant="primary")
                yield Button("Cancel", id="upload_cancel_btn", variant="error")

    def on_mount(self) -> None:
        table = self.query_one("#upload_fs_table", DataTable)
        table.clear(columns=True)
        table.add_columns("Name", "Type", "Size", "Modified")
        self._refresh_entries()
        table.focus()

    def _refresh_entries(self) -> None:
        table = self.query_one("#upload_fs_table", DataTable)
        entries: list[LocalFsEntry] = []
        self.status_message = "Enter: abrir pasta | U: fazer upload | Backspace: pasta pai"
        parent = self.current_dir.parent
        if parent != self.current_dir:
            entries.append(LocalFsEntry(path=parent, name="..", kind="parent"))

        try:
            dirs: list[LocalFsEntry] = []
            files: list[LocalFsEntry] = []
            for child in self.current_dir.iterdir():
                try:
                    stat = child.stat()
                except OSError:
                    continue
                modified = datetime.fromtimestamp(stat.st_mtime)
                if child.is_dir():
                    dirs.append(LocalFsEntry(path=child, name=child.name, kind="dir", modified=modified))
                else:
                    files.append(
                        LocalFsEntry(
                            path=child,
                            name=child.name,
                            kind="file",
                            size=int(stat.st_size),
                            modified=modified,
                        )
                    )
            dirs.sort(key=lambda item: item.name.lower())
            files.sort(key=lambda item: item.name.lower())
            entries.extend(dirs)
            entries.extend(files)
        except OSError as error:
            self.status_message = f"Filesystem error: {error}"

        self.entries = entries
        table.clear()
        for entry in self.entries:
            size = "" if entry.kind != "file" else self._human_size(entry.size)
            modified = entry.modified.isoformat(sep=" ", timespec="seconds") if entry.modified else ""
            table.add_row(entry.name, entry.kind, size, modified)

        self.query_one("#upload_current_path", Static).update(str(self.current_dir))
        self.query_one("#upload_status", Static).update(self.status_message)
        if self.entries:
            try:
                table.move_cursor(row=0, column=0)
            except Exception:
                pass

    def _selected_entry(self) -> LocalFsEntry | None:
        table = self.query_one("#upload_fs_table", DataTable)
        if not self.entries:
            return None
        row_index = table.cursor_coordinate.row
        if row_index < 0 or row_index >= len(self.entries):
            return None
        return self.entries[row_index]

    def action_open_or_select(self) -> None:
        selected = self._selected_entry()
        if selected is None:
            return
        if selected.kind in {"dir", "parent"}:
            try:
                self.current_dir = selected.path.resolve()
                self._refresh_entries()
            except OSError as error:
                self.status_message = f"Cannot open folder: {error}"
                self.query_one("#upload_status", Static).update(self.status_message)
            return
        self.status_message = "Press U to upload selected file."
        self.query_one("#upload_status", Static).update(self.status_message)

    def action_go_parent(self) -> None:
        parent = self.current_dir.parent
        if parent != self.current_dir:
            try:
                self.current_dir = parent.resolve()
                self._refresh_entries()
            except OSError as error:
                self.status_message = f"Cannot open parent: {error}"
                self.query_one("#upload_status", Static).update(self.status_message)

    def action_upload_selected(self) -> None:
        selected = self._selected_entry()
        if selected is None:
            return
        if selected.kind == "parent":
            self.action_go_parent()
            return
        self.dismiss(selected.path)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        # CellSelected ainda é emitido pelo clique do mouse (não pelo Enter,
        # pois action_select_cursor foi sobrescrito acima).
        # Usamos para detectar double-click do mouse.
        if event.data_table.id != "upload_fs_table":
            return
        now = monotonic()
        row = event.coordinate.row
        is_double_click = (
            self._last_mouse_click_row == row
            and (now - self._last_mouse_click_ts) <= 0.45
        )
        self._last_mouse_click_row = None
        self._last_mouse_click_ts = 0.0
        if is_double_click:
            selected = self._selected_entry()
            if selected and selected.kind in {"dir", "parent"}:
                self.action_open_or_select()

    def on_click(self, event: Click) -> None:
        if event.widget and event.widget.id == "upload_fs_table":
            table = self.query_one("#upload_fs_table", DataTable)
            self._last_mouse_click_row = table.cursor_coordinate.row
            self._last_mouse_click_ts = monotonic()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "upload_select_btn":
            self.action_upload_selected()
        elif event.button.id == "upload_cancel_btn":
            self.action_cancel()

    @staticmethod
    def _human_size(size: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"


class S3TUI(App[None]):
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
        Binding("d", "download_selected", "Download"),
        Binding("u", "upload_selected", "Upload"),
        Binding("c", "copy_selected", "Copy"),
        Binding("m", "move_selected", "Move"),
        Binding("delete", "delete_selected", "Delete"),
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
                    yield Button("Upload", id="upload_btn", variant="primary")
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

    def _table(self) -> DataTable:
        return self.query_one("#left_table", DataTable)

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

    def _clear_search(self) -> None:
        self.search_query = ""
        self._search_hint().update("")
        search_input = self.query_one("#search_input", Input)
        if search_input.value:
            search_input.value = ""

    def _init_table(self, table: DataTable) -> None:
        if hasattr(table, "cursor_type"):
            table.cursor_type = "cell"
        if hasattr(table, "show_cursor"):
            table.show_cursor = True
        if hasattr(table, "zebra_stripes"):
            table.zebra_stripes = True
        table.clear(columns=True)
        table.add_columns("Name", "Type", "Size", "Modified")

    def _log(self, message: str) -> None:
        self._preview().write(message)

    def _show_log_preview(self) -> None:
        self._preview_table().display = False
        self._preview().display = True

    def _show_table_preview(self) -> None:
        self._preview().display = False
        self._preview_table().display = True

    def _preview_widget(self) -> DataTable | RichLog:
        table = self._preview_table()
        return table if table.display else self._preview()

    def _scroll_preview_horizontal(self, delta: int) -> None:
        widget = self._preview_widget()
        widget.scroll_to(x=widget.scroll_x + delta, y=widget.scroll_y, animate=False)

    def _selected_entry(self) -> S3Entry | None:
        try:
            table = self._table()
        except NoMatches:
            return None
        if not self.left.entries:
            return None
        row_index = table.cursor_coordinate.row
        if row_index < 0 or row_index >= len(self.left.entries):
            return None
        return self.left.entries[row_index]

    def _render_entries(self) -> None:
        table = self._table()
        table.clear()
        for entry in self.left.entries:
            kind = {
                "bucket": "bucket",
                "parent": "..",
                "dir": "dir",
                "file": "file",
            }[entry.kind]
            size = "" if entry.kind != "file" else self._human_size(entry.size)
            modified = entry.modified.isoformat(sep=" ", timespec="seconds") if entry.modified else ""
            table.add_row(entry.name, kind, size, modified)

        self._path_widget().update(self.left.path)
        self._select_first_row()
        self._update_search_hint()
        self._update_right_info(self._selected_entry())

    def _select_first_row(self) -> None:
        if not self.left.entries:
            return
        table = self._table()
        try:
            table.move_cursor(row=0, column=0)
        except Exception:
            pass

    def _apply_filter(self) -> None:
        query = self.search_query.strip().lower()
        if not query:
            self.left.entries = list(self.left.all_entries)
            self._render_entries()
            return

        filtered: list[S3Entry] = []
        for entry in self.left.all_entries:
            if entry.kind == "parent":
                filtered.append(entry)
                continue
            if query in entry.name.lower():
                filtered.append(entry)

        self.left.entries = filtered
        self._render_entries()

    def _update_search_hint(self) -> None:
        query = self.search_query.strip().lower()
        if not query:
            self._search_hint().update("")
            return

        for entry in self.left.all_entries:
            if entry.kind == "parent":
                continue
            if entry.name.lower().startswith(query):
                self._search_hint().update(f"Autocomplete: {entry.name}")
                return
            if query in entry.name.lower():
                self._search_hint().update(f"Match: {entry.name}")
                return

        self._search_hint().update("No results")

    @staticmethod
    def _human_size(size: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} B"

    def _refresh_left(self) -> None:
        try:
            if self.left.mode == "buckets":
                self.left.all_entries = self.service.list_buckets()
            else:
                self.left.all_entries = self.service.list_prefix(bucket=self.left.bucket or "", prefix=self.left.prefix)
            self._apply_filter()
        except (BotoCoreError, ClientError) as error:
            self._log(f"S3 error: {error}")

    def _entry_uri(self, entry: S3Entry) -> str:
        if entry.kind == "bucket":
            return f"s3://{entry.name}/"
        if self.left.bucket is None:
            return entry.name
        if entry.kind == "parent":
            return f"s3://{self.left.bucket}/{self.left.prefix}.."
        return f"s3://{self.left.bucket}/{entry.key}"

    def _update_right_info(self, entry: S3Entry | None) -> None:
        if entry is None:
            self._right_info().update("No item selected.")
            return

        modified = entry.modified.isoformat(sep=" ", timespec="seconds") if entry.modified else "-"
        size = self._human_size(entry.size) if entry.kind == "file" else "-"
        details = (
            f"Name: {entry.name}\n"
            f"Type: {entry.kind}\n"
            f"URI: {self._entry_uri(entry)}\n"
            f"Size: {size}\n"
            f"Modified: {modified}\n"
            f"Context: {self.left.path}"
        )
        self._right_info().update(details)

    def _open_entry(self, entry: S3Entry) -> None:
        if self.left.mode == "buckets" and entry.kind == "bucket":
            self._clear_search()
            self.left.mode = "objects"
            self.left.bucket = entry.name
            self.left.prefix = ""
            self._refresh_left()
            return

        if self.left.mode != "objects":
            return

        if entry.kind == "parent":
            self._go_up()
            return

        if entry.kind == "dir":
            self._clear_search()
            self.left.prefix = entry.key
            self._refresh_left()
            return

        if entry.kind == "file":
            self._preview_file(entry)

    def _go_up(self) -> None:
        if self.left.mode == "buckets":
            return

        self._clear_search()
        if not self.left.prefix:
            self.left.mode = "buckets"
            self.left.bucket = None
            self.left.prefix = ""
            self._refresh_left()
            return

        parts = self.left.prefix.rstrip("/").split("/")
        parent_parts = parts[:-1]
        self.left.prefix = ("/".join(parent_parts) + "/") if parent_parts else ""
        self._refresh_left()

    def _preview_file(self, entry: S3Entry) -> None:
        if self.left.bucket is None or entry.kind != "file":
            return

        if entry.size > 25 * 1024 * 1024:
            self._log(f"Preview blocked: large file ({self._human_size(entry.size)}).")
            return

        try:
            content = self.service.read_object(self.left.bucket, entry.key)
            if is_image_file(entry.name):
                self._show_log_preview()
                self._preview().clear()
                self._log(f"Preview: s3://{self.left.bucket}/{entry.key}")
                self._render_image_preview(content)
                return

            table_preview = build_table_preview(entry.name, content)
            if table_preview is not None:
                columns, rows = table_preview
                table = self._preview_table()
                table.clear(columns=True)
                if not columns:
                    columns = ["value"]
                table.add_columns(*columns)
                for row in rows:
                    table.add_row(*row)
                if hasattr(table, "show_cursor"):
                    table.show_cursor = True
                if hasattr(table, "zebra_stripes"):
                    table.zebra_stripes = True
                self._show_table_preview()
                table.move_cursor(row=0, column=0)
            else:
                text = build_preview(entry.name, content)
                self._preview().clear()
                self._show_log_preview()
                self._log(f"Preview: s3://{self.left.bucket}/{entry.key}")
                self._log(text)
        except Exception as error:
            self._show_log_preview()
            self._log(f"Preview failed: {error}")

    def _render_image_preview(self, content: bytes) -> None:
        if PILImage is None:
            self._log("Image preview requires Pillow. Run: poetry install")
            return

        try:
            image = PILImage.open(io.BytesIO(content))
            image.load()
            original_size = image.size
            image.thumbnail((400, 400))

            renderable = self._build_rich_image(image)
            if renderable is not None:
                self._preview().write(renderable)
            else:
                self._log("Rich image unavailable; using ASCII preview.")
                self._log(self._image_to_ascii(image))
            self._log(f"Image size: {original_size[0]}x{original_size[1]} -> {image.size[0]}x{image.size[1]}")
        except UnidentifiedImageError:
            self._log("Invalid image file.")

    @staticmethod
    def _build_rich_image(image: PILImage.Image) -> object | None:
        if RichImage is None:
            return None

        builders = [
            lambda: RichImage(image),
            lambda: RichImage.from_pil(image),  # type: ignore[attr-defined]
        ]
        for build in builders:
            try:
                return build()
            except Exception:
                continue
        return None

    @staticmethod
    def _image_to_ascii(image: PILImage.Image, max_width: int = 120) -> str:
        grayscale = image.convert("L")
        width, height = grayscale.size
        if width <= 0 or height <= 0:
            return "[empty image]"

        target_width = min(width, max_width)
        target_height = max(1, int((height / width) * target_width * 0.55))
        resized = grayscale.resize((target_width, target_height))
        pixels = list(resized.getdata())
        gradient = " .:-=+*#%@"
        scale = len(gradient) - 1

        lines: list[str] = []
        for y in range(target_height):
            row = pixels[y * target_width : (y + 1) * target_width]
            line = "".join(gradient[value * scale // 255] for value in row)
            lines.append(line.rstrip() or " ")
        return "\n".join(lines)

    def action_open_selected(self) -> None:
        entry = self._selected_entry()
        if entry:
            self._open_entry(entry)

    def action_go_up(self) -> None:
        self._go_up()

    def action_preview_selected(self) -> None:
        entry = self._selected_entry()
        if entry and entry.kind == "file":
            self._preview_file(entry)

    def action_preview_page_down(self) -> None:
        self._preview_widget().scroll_page_down(animate=False)

    def action_preview_page_up(self) -> None:
        self._preview_widget().scroll_page_up(animate=False)

    def action_preview_scroll_left(self) -> None:
        self._scroll_preview_horizontal(-8)

    def action_preview_scroll_right(self) -> None:
        self._scroll_preview_horizontal(8)

    def action_refresh(self) -> None:
        self._refresh_left()

    def action_download_selected(self) -> None:
        entry = self._selected_entry()
        if not entry or entry.kind != "file" or self.left.bucket is None:
            return

        destination = Path("downloads") / self.left.bucket / entry.key
        try:
            self.service.download(self.left.bucket, entry.key, destination)
            self._log(f"Download: s3://{self.left.bucket}/{entry.key} -> {destination}")
        except Exception as error:
            self._log(f"Download failed: {error}")

    def action_upload_selected(self) -> None:
        if self.left.mode != "objects" or self.left.bucket is None:
            self._log("Upload unavailable: select a bucket/path in pane 1 first.")
            return

        self.push_screen(UploadPickerScreen(Path.home()), self._on_upload_picked)

    def _on_upload_picked(self, selected_path: Path | None) -> None:
        if selected_path is None:
            return
        if self.left.mode != "objects" or self.left.bucket is None:
            self._log("Upload aborted: no destination bucket selected.")
            return

        destination_prefix = self.left.prefix or ""
        bucket = self.left.bucket
        try:
            if selected_path.is_file():
                key = f"{destination_prefix}{selected_path.name}"
                self.service.upload_file(bucket, key, selected_path)
                self._log(f"Uploaded file: {selected_path} -> s3://{bucket}/{key}")
            elif selected_path.is_dir():
                target_prefix = f"{destination_prefix}{selected_path.name}"
                uploaded_count = self.service.upload_directory(bucket, selected_path, prefix=target_prefix)
                self._log(
                    f"Uploaded folder: {selected_path} -> s3://{bucket}/{target_prefix}/ "
                    f"({uploaded_count} files)"
                )
            else:
                self._log(f"Upload failed: invalid path {selected_path}")
                return
            self._refresh_left()
        except Exception as error:
            self._log(f"Upload failed: {error}")

    def action_copy_selected(self) -> None:
        self._log("Copy is disabled in this layout (right panel = details).")

    def action_move_selected(self) -> None:
        self._log("Move is disabled in this layout (right panel = details).")

    def action_delete_selected(self) -> None:
        entry = self._selected_entry()
        if not entry or entry.kind != "file" or self.left.bucket is None:
            return

        try:
            self.service.delete(self.left.bucket, entry.key)
            self._refresh_left()
            self._log(f"Deleted: s3://{self.left.bucket}/{entry.key}")
        except Exception as error:
            self._log(f"Delete failed: {error}")

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
        row = event.coordinate.row
        if event.data_table.id == self.left.table_id and 0 <= row < len(self.left.entries):
            self._update_right_info(self.left.entries[row])

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        row = event.coordinate.row
        if event.data_table.id == self.left.table_id and 0 <= row < len(self.left.entries):
            entry = self.left.entries[row]
            self._update_right_info(entry)
            now = monotonic()
            is_double_click = self._last_click_row == row and (now - self._last_click_ts) <= 0.45
            self._last_click_row = row
            self._last_click_ts = now
            if is_double_click:
                self._open_entry(entry)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search_input":
            self.search_query = event.value
            self._apply_filter()

    def on_key(self, event: Key) -> None:
        if isinstance(self.screen, UploadPickerScreen):
            return
        if event.key == "enter":
            self.action_open_selected()

    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        if event.shift:
            self._scroll_preview_horizontal(-4)
            event.stop()

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        if event.shift:
            self._scroll_preview_horizontal(4)
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "upload_btn":
            self.action_upload_selected()


def main() -> None:
    S3TUI().run()


if __name__ == "__main__":
    main()