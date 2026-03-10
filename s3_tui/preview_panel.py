from __future__ import annotations

import io

from s3_tui.preview import build_preview, build_table_preview, is_image_file

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


class PreviewMixin:
    def _log(self, message: str) -> None:
        self._preview().write(message)

    def _show_log_preview(self) -> None:
        self._preview_table().display = False
        self._preview().display = True

    def _show_table_preview(self) -> None:
        self._preview().display = False
        self._preview_table().display = True

    def _preview_widget(self):
        table = self._preview_table()
        return table if table.display else self._preview()

    def _scroll_preview_horizontal(self, delta: int) -> None:
        widget = self._preview_widget()
        widget.scroll_to(x=widget.scroll_x + delta, y=widget.scroll_y, animate=False)

    def _preview_file(self, entry) -> None:
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
