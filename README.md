# obsidian-ai-miniserver

A complete Obsidian tool in ~320 tokens! ([see tool_prompt.md](https://raw.githubusercontent.com/whogben/obsidian_ai_miniserver/main/tool_prompt.md))

Makes your Obsidian vault accessible via REST API (OpenAPI) and a streamable HTTP MCP server. Enables AI to find, read, and edit text notes. Supports multiple users with token-based auth and path-level access control.

Browse the API on [Redocly](https://redocly.github.io/redoc/?url=https://raw.githubusercontent.com/whogben/obsidian_ai_miniserver/main/openapi.json) or [Swagger](https://petstore.swagger.io/?url=https://raw.githubusercontent.com/whogben/obsidian_ai_miniserver/main/openapi.json).

<img src="https://raw.githubusercontent.com/whogben/obsidian_ai_miniserver/main/docs/images/screenshot_home.png" alt="Home page showing admin user" width="600">

## What's good about it

### Maximum Control
- Works for any form of text files in vault — markdown, json, etc
- AI can do advanced regex searches
- Limits, Paging, Sort on all requests — AI can adjust snippet sizes on search results, no more tokens than it needs
- Every call is a batch — multiple operations in one round-trip by default saves time and tokens
- Create multiple users with their own keys, different read/write permissions and folder access
- Keep your personal vault personal — while enabling agents access to specific subsets

<img src="https://raw.githubusercontent.com/whogben/obsidian_ai_miniserver/main/docs/images/screenshot_users.png" alt="Users list" width="500">

### Maximum Flexibility
- **Access anywhere** — WebUI for humans, MCP http streaming for agents, OpenAPI for integrations
- **Run anywhere** — Locally with Obsidian app, headless in container, with Obsidian Sync or just from folder
- **Compatibility built-in** — Agent harness dropping rich parameter schemas? We collapse the schema into the function docstring and accept a plain JSON string

<img src="https://raw.githubusercontent.com/whogben/obsidian_ai_miniserver/main/docs/images/screenshot_user.png" alt="User detail with access rules" width="500">

### Maximum Token Efficiency = Faster and Cheaper
- Single CLI command, single tool interface for AI
- AI can perform all admin work — once connected, it takes over setup for you
- Maximally powerful requests to minimize request and param counts
- The entire tool schema uses ~320 tokens thanks to minimized docstrings, zero duplication or boilerplate — see [tool_prompt.md](https://raw.githubusercontent.com/whogben/obsidian_ai_miniserver/main/tool_prompt.md)
- ~50% token savings vs raw FastMCP generated schemas with no information loss

## Quick start

```bash
pip install obsidian-ai-miniserver
obs_ai_ms start /path/to/vault --admin-token your_token
```

This starts both servers on their default ports. Connect your AI to the MCP endpoint or the REST API.

<img src="https://raw.githubusercontent.com/whogben/obsidian_ai_miniserver/main/docs/images/screenshot_login.png" alt="Login page" width="400">

## Options

| Option | Env Var | Default | Description |
| --- | --- | --- | --- |
| `vault_path` | — | *(required)* | Path to the Obsidian vault |
| `--admin-token` | `OBS_AI_MS_ADMIN_TOKEN` | *(none)* | Auth token for the admin user |
| `--port` | `OBS_AI_MS_PORT` | `8747` | Server port |
| `--host` | `OBS_AI_MS_HOST` | `127.0.0.1` | Host to bind to. Use `0.0.0.0` to allow remote access |
| `--fqdn` | `OBS_AI_MS_FQDN` | *(none)* | Public URL for self-linking |
| `--base-path` | `OBS_AI_MS_BASE_PATH` | *(none)* | Base path when behind a reverse proxy |

<img src="https://raw.githubusercontent.com/whogben/obsidian_ai_miniserver/main/docs/images/screenshot_config.png" alt="Config page" width="500">

## Persistence

Config is stored at `.obsidian/obsidian_ai_miniserver.json` inside the vault — user list with tokens and path access rules.

<img src="https://raw.githubusercontent.com/whogben/obsidian_ai_miniserver/main/docs/images/screenshot_add_user.png" alt="Add user page" width="500">

## Headless deployment

Run headless in a Docker container with [Obsidian Headless](https://obsidian.md/sync) — no desktop app needed. The [`docker-compose.yaml`](docker-compose.yaml) is fully self-contained: it installs everything from the internet at startup.

You can paste it directly into a container platform like [Coolify](https://coolify.io) — just set the environment variables:

| Env Var | Description |
| --- | --- |
| `OBSIDIAN_USERNAME` | Your Obsidian account email |
| `OBSIDIAN_PASSWORD` | Your Obsidian account password |
| `OBSIDIAN_VAULTNAME` | Name of your remote vault |
| `OBS_AI_MS_ADMIN_TOKEN` | Admin auth token |
| `OBS_AI_MS_HOST` | Host to bind to (default `0.0.0.0`) |
| `OBS_AI_MS_PORT` | Server port (default `8747`) |
| `OBS_AI_MS_FQDN` | Public URL for self-linking |
| `OBS_AI_MS_BASE_PATH` | Base path when behind a reverse proxy |

Or via CLI:

```bash
OBSIDIAN_USERNAME=you@example.com OBSIDIAN_PASSWORD=secret OBSIDIAN_VAULTNAME="My Vault" docker compose up
```

## API reference

All requests go to `POST /api/obsidian` as a JSON array of request objects, each with a `kind` field that discriminates the request type. Available kinds:

- `get_vault_info` — vault name, daily notes folder, your user info
- `list_files` — list files and folders at a path
- `read_text` — read a note's text
- `write_text` — overwrite a note
- `append_text` — append to a note
- `replace_text` — find and replace text in a note
- `move_file` — move, copy, or delete a file
- `search_files` — regex search across notes and text files with context snippets
- `list_users` / `upsert_user` — admin user management
