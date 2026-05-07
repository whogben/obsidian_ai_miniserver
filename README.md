# obsidian-ai-miniserver

Makes your Obsidian vault accessible via REST API (OpenAPI) and a streamable HTTP MCP server. Enables AI to find, read, and edit text notes. Supports multiple users with token-based auth and path-level access control.

## Quick start

```bash
pip install obsidian-ai-miniserver
obs_ai_ms start /path/to/vault --admin-token your_token
```

This starts both servers on their default ports. Connect your AI to the MCP endpoint or the REST API.

## Options

| Option | Default | Description |
| --- | --- | --- |
| `vault_path` | *(required)* | Path to the Obsidian vault |
| `--admin-token` | *(required)* | Auth token for the admin user |
| `--openapi-port` | `8747` | Port for the REST API server (`-1` to disable) |
| `--mcp-port` | `8716` | Port for the MCP server (`-1` to disable) |
| `--host` | `127.0.0.1` | Host to bind to. Use `0.0.0.0` to allow remote access |

## Persistence

Config is stored at `.obsidian/obsidian_ai_miniserver.json` inside the vault — user list with tokens and path access rules.

## API reference

See [`openapi.json`](https://github.com/whogben/obsidian_ai_miniserver/blob/main/openapi.json) for full request/response definitions.

All requests go to `POST /api/obsidian` with a `kind` field that discriminates the request type. Available kinds:

- `get_vault_info` — vault name, daily notes folder, your user info
- `list_files` — list files and folders at a path
- `read_text` — read a note's text
- `write_text` — overwrite a note
- `append_text` — append to a note
- `replace_text` — find and replace text in a note
- `move_file` — move, copy, or delete a file
- `list_users` / `upsert_user` — admin user management
