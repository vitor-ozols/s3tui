# s3-tui

Python TUI to explore S3 in a commander-style layout, focused on navigation plus selection details.

## Implemented features

- Bucket and prefix navigation (left pane)
- Right pane with real-time details for the currently selected item on the left
- Real-time search with autocomplete/match hints (example: typing `bi` suggests `bi-cws`)
- File preview for:
  - CSV
  - JSON / JSONL / NDJSON
  - Parquet
  - text files (txt, log, md, etc.)
- Download to `./downloads/<bucket>/<key>`
- File delete

## Requirements

- Python 3.11+
- AWS credentials configured (`~/.aws/credentials`, environment variables, or IAM role)

## Install

```bash
poetry install
```

## Run

```bash
poetry run s3tui
```

## Shortcuts

- Search field (top-left): filters in real time
- `ENTER`: open bucket/folder or preview file
- `BACKSPACE`: go up one level
- `P`: preview selected file
- `D`: download selected file
- `DELETE`: delete selected file
- `R`: refresh listing
- `Q`: quit

## Notes

- In this layout, the right pane is informational only.
- `Copy` and `Move` are currently disabled because there is no destination pane.
