# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.2] - 2026-05-07

### Fixed

- Fixed openapi.json link in README

## [0.1.1] - 2026-05-07

### Added

- PyPI package description and readme
- OpenWebUI compatibility fixes
- Review fixes

## [0.1.0] - 2026-05-06

### Added

- REST API server (OpenAPI) and streamable HTTP MCP server for Obsidian vaults
- Token-based authentication with path-level access control
- `get_vault_info` — vault name, daily notes folder, user info
- `list_files` — recursive file and folder listing with sorting and pagination
- `read_text` — read note text with offset/limit
- `write_text` — overwrite a note
- `append_text` — append text to a note
- `replace_text` — find and replace text in a note
- `move_file` — move, copy, or delete files
- `list_users` / `upsert_user` — admin user management
- Config persisted at `.obsidian/obsidian_ai_miniserver.json` inside the vault
- CLI: `obs_ai_ms start <vault_path> --admin_token <token>`
