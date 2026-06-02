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
  - images (PNG, JPG, JPEG, GIF, BMP, WEBP, TIFF) up to 400x400
  - rendered Markdown (MD, Markdown, MDOWN, MKDN)
  - text files (txt, log, etc.)
- Download to `./downloads/<bucket>/<key>`
- Delete for files and directories
- Create directories
- Move files and directories with S3 destination picker

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

## Run with Docker

You can also run `s3-tui` inside a Docker container using Docker Compose. This ensures all dependencies are isolated and it automatically maps your local AWS credentials.

### Prerequisites
- Docker and Docker Compose installed.
- AWS credentials configured locally in `~/.aws`.

### Running the container

Since `s3-tui` is an interactive terminal UI, you must run it with interactive tty flags enabled. Run the following command in your terminal:

```bash
docker compose run --rm s3-tui
```

This command will build the image (if not already built) and launch the TUI seamlessly. Any downloaded files will be saved into the `./downloads` folder on your host machine.

## Shortcuts

- Search field (top-left): filters in real time
- `ENTER`: open bucket/folder or preview file
- `BACKSPACE`: go up one level
- `P`: preview selected file
- `Shift+D`: download selected file
- `N`: open create-directory dialog
- `U`: open upload picker (file or folder)
- `M`: open move dialog and choose the destination in S3
- `D`: delete selected file or directory (asks for confirmation with `Y/N`)
- `R`: refresh listing
- `Q`: quit

## Notes

- `Copy` and `Move` are currently disabled because there is no destination pane.