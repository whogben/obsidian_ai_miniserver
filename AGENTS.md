# AGENTS.md

## Project Overview

Obsidian AI Mini Server (`obs_ai_ms`) — a Python package that exposes an Obsidian vault to AI agents via a REST API (FastAPI) and an MCP streamable HTTP server (FastMCP). See `SPEC.md` for the full design spec and `src/obs_ai_ms/models.py` for the request/response schemas.

This is a **greenfield project** — only `SPEC.md` and `models.py` exist. Key files like `entry.py`, `vault.py`, tests, and `scripts/publish.py` are described in the spec but not yet implemented.

## Cursor Cloud specific instructions

- **Python venv**: Always use `.venv/bin/python` (or activate `.venv`) — never use system Python. The venv is at the project root.
- **Package install**: The project uses `uv` for fast dependency management. Run `uv pip install -e .` from `/workspace` to install the package in editable mode. Dev tools (pytest, ruff, httpx) are installed separately: `uv pip install pytest pytest-asyncio httpx ruff`.
- **Lint**: `ruff check src/` — config is in `pyproject.toml` (rules: E, F, I, W; line-length 100).
- **Tests**: `pytest` — test paths configured to `tests/` in `pyproject.toml`. No tests exist yet.
- **Known warning**: `models.py` emits `UserWarning: Field name "copy" in "MoveFile" shadows an attribute in parent "BaseRequest"` — this is from the existing code and is harmless.
- **No running servers yet**: `entry.py` (CLI entrypoint) and `vault.py` (core logic) do not exist. The project cannot serve HTTP until those are implemented.
- **Assumed `.env` file**: A `.env` file may exist at project root (gitignored) — do not create or modify it.
