
## Design

**Goals**
- Make one or more Obsidian vaults accessible via multiple AI-friendly interfaces:
	- `/api` for OpenAPI (`/api/openapi.json`)
	- `/web` for Web UI
	- `/mcp` for MCP server (streamable HTTP)
- Enable AI to easily find, read and edit text notes across vaults.
- Allow for multiple users with limited access, identified by token sent in `Authorization: Bearer` headers.
- Users can be granted access to specific vaults with per-vault path permissions.

**Setup**
- Installable via pip `pip install obsidian-ai-miniserver`
- Runnable with command `obs_ai_ms start <any optional args>`
	- Optional Args:
		- `--vault` — vault to register, as `name:path`, repeatable. e.g. `--vault work:/path/to/work --vault personal:sync:/path/to/personal`. If name matches existing vault, no change. If path matches existing vault under different name, updates the name. Path starting with `sync:` creates the dir and syncs the Obsidian vault named after the final dir into it. e.g. `--vault notes:sync:/vaults/MyNotes` syncs Obsidian vault "MyNotes" into `/vaults/MyNotes`, locally aliased as "notes".
		- `--admin-token` — sets user 0's token
		- `--port` — server port (default `8747`)
		- `--host` — host to bind to (default `127.0.0.1`)
		- `--fqdn` — public URL of this server so it can generate links to itself, e.g. `https://yourdomain.com`
		- `--base-path` — base path when behind a reverse proxy
		- `--config` — path to config file (default: platform app support dir)
		- `--obs-username` — Obsidian account email for headless sync (optional)
		- `--obs-password` — Obsidian account password for headless sync (write-only, never returned by API)
		- Each option can also be set via an env var: `OBS_AI_MS_` plus the SCREAMING_SNAKE form of the flag name, e.g. `OBS_AI_MS_ADMIN_TOKEN`, `OBS_AI_MS_PORT`, `OBS_AI_MS_BASE_PATH`.
	- Can be started with no vaults — add them later via web admin or API
	- Outputs the interface URLs and API docs url on start

**Use**
- Connect your AI to the MCP or the Open API tool server.
- It can now make requests via the obsidian tool
- Visit `127.0.0.1:<port>/web` for a GUI admin interface for vault, status and user management.

**Single Tool Interface**
A single function interface accepts different kinds of requests and returns different kinds of responses.
- `obsidian(requests: str) -> str`
	- Accepts a JSON string of request objects: `"[{"kind":"..", ..}, ..]"`
	- Returns a JSON string of response objects: `[{"kind":"..", ..}]`
	- The full request/response schemas are embedded in the function description as compact text, not in the parameter schema
		- schema begins as full json-schema of each type
		- extract any duplicate / uneccesary / obvious keys that aren't adding information that isn't obvious
		- compress the representation so that the "kind" key doesn't need to be repeated
	- This maximizes compatibility with clients that drop rich parameter schemas (OpenAPI `oneOf`, MCP complex types)
	- OpenAPI: POST `/api/obsidian` with JSON body `{"requests": "<json array string>"}` (schema in description)
	- MCP: `obsidian(requests: str) -> str` tool (schema in docstring)
- Request and Response objects
	- subclass common BaseRequest and BaseResponse
	- `kind` string literal discriminates subclasses
	- The request class docstr is the primary per-tool documentation

**Run Next to Obsidian**
You can run it on the same computer you run Obsidian on, pointing it at one or more vault folders.

**Run Headless in Container**
Alternatively, you can run it in a container with just the Obsidian sync service, which is much less RAM and overhead than running full electron-based Obsidian. This is optimal for making Obsidian content available via headless cloud server. Supports syncing multiple vaults. Configure `--obs-username`, `--obs-password` and register vaults with `sync:` prefixed paths — the server handles obsidian-headless installation, authentication, `sync-setup`, `sync-config` with all `ob` file-type buckets, then continuous sync. Vaults remain accessible from disk even if sync is temporarily unavailable.

----
## Implementation

**Identities**
- Project: github.com/whogben/obsidian_ai_miniserver
- Package: pypi.org/obsidian-ai-miniserver
- Author: William Hogben
- Homepage: willhogben.com

**Layout**
- SPEC.md (this file)
- src/
	- obs_ai_ms/
		- entry.py <- CLI command runs this
		- models.py <- Defines requests, responses, and webui
		- vault.py <- Vault class with the  tool function
		- sync.py <- Manages obsidian-headless CLI for sync-managed vaults
		- webui.py <- All the `/web` interface details
- tests/
	- test_vault.py
	- test_integration.py
- scripts/
	- publish.py <- tests, builds, publishes
	- update_screenshots.py
- docs/
	- images/
		screenshot_< name >.png
- pyproject.toml
- tool_prompt.md <- current tool description given to AI
- README.md
- openapi.json <- current OpenAPI spec
- CHANGELOG.md
- docker-compose.yaml <- used to deploy headless
- AGENTS.md <- optional extra context for future ai maintainers

**Dependencies**
- fastapi
- fastmcp
- platformdirs
- pydantic
- typer
- uvicorn
- Node.js runtime (optional — only needed when sync-managed vaults are configured)

**Tests Validate**
- Each real interface works, e.g. real CLI test, real HTTP, real MCP
- Each CLI command w/ variation for each optional param
- Each major mode and branch of each requestable and outward facing interface.
- Path resolution and multi-vault commands, cross-vault commands.
- Real connectivity of the mcp and api servers with and without auth.
- Automatically updates the project root's openapi.json if it has changed
- Automatically updates the project root's tool_prompt if is has changed.
- Web pages return some of the expected information.
- Committed screenshots under `docs/images/` match the web UI produced by `update_screenshots.py` for the scripted test vault (regenerate that script when `/web` pages change materially)
- The "~ < X > tokens" in the README is counted via tiktoken (cl100k_base / gpt-4o) on the MCP tool schema


**SPEC.md**
This human-maintained spec file defines the project as a whole.
- Changes to the spec can cascade or any other part of the project.

**models.py**
This human-maintained schemas file details the project’s inputs and outputs and web ui elements.
- TOOL_PROMPT template used for tool function docstring.
- Single source of truth on all of the possible request and response types with all public information about a tool’s inputs and outputs.
- Request implementations are to be derived from this file and updated when this file changes. 
- Web UI pages are described by models descending BasePage.
- Auth is handled via cookie.

**vault.py**
Defines the main service class, Vault, which:
- accesses one or more vault folders using cross-platform Python file commands
- "obsidian" method accepts a list of requests and returns a list of responses.
- implements all requests
- checks for a .obsidian/daily-notes.json within each vault {"folder":"PathTo/Dailies"} to locate a non-root the daily notes folder.
- handles vault-aware pathing:
	- a user with access to one vault can send paths as-is, no vault awareness, and receive normal paths back
	- a user with access to 2+ vaults must send vault-aware paths, e.g. "vaultname:vaultpath"
	- a path of "*:" applies to all vaults, and path "" is equivalent to that.
	- a path that is not vault aware will be rejected if a user has 2+ vaults, and the user can use GetVaultsInfo to see what vault names are and retry
	- Non-admins can find out about the vaults they have access to.
	- Multivault files/search etc results are 1. combined, 2. sorted, 3. limited and offset all together.
	- `move_file` rename within a vault: scan markdown the user may write for wikilinks and Markdown links to the old path, rewrite to the new path; wikilink `[[basename]]` targets the last segment of the moved path (Obsidian-style); `success.message` when any file changed (see `Success` in models).

**sync.py**
Manages the obsidian-headless CLI (`ob`) for vaults whose dir_path starts with `sync:`.
- On startup, if `obs_username` is set and sync vaults exist:
	- ensure `ob` is installed (`npm install -g obsidian-headless` if missing)
	- authenticate via `ob login`
	- for each sync vault: `mkdir -p`, `ob sync-setup`, `ob sync-config` (all `--file-types`), `ob sync --continuous` as a child subprocess
- Remote vault name = `basename(local_path)` — e.g. `sync:/vaults/MyNotes` syncs Obsidian vault "MyNotes"
- All sync processes are children of the server — they stop when it stops
- Tracks running processes by vault name to prevent double-starting
- Captures stdout+stderr into a thread-safe ring buffer (last 200 lines)
- Exposes `get_recent_log(n)` and `get_latest_line()` (returns None if >30s old)
- Graceful degradation: if credentials fail or sync is down, vault still serves from disk

**webui.py**
Implements the web routes that are defined in models.py, providing all web ui related functionality.
- Returns clean and mininamlist HTML via fstrings.
- Able to render pages from the BasePage descendant models.
- Minimal CSS style based on dark-gray thats acceptable for users of dark modes

**tool_prompt.md**
Generated description contains all critical tool info and parameter details in a format shorter than json schema.

**persistence**
Config data is persisted in a central config file outside any vault.
- Default location: platform application support directory (e.g. `~/Library/Application Support/obsidian_ai_miniserver/` on macOS, `~/.config/obsidian_ai_miniserver/` on Linux)
- Overridable via `--config` flag or `OBS_AI_MS_CONFIG` env var
- Contains: vaults, users, server settings
- On first run with no config: creates default config with generated admin token, prints token to stdout

**entry.py**
Run by the CLI command to start the combined server with OpenAPI, Streamable HTTP MCP, and the Web UI
- creates a shared Vault instance (which may hold zero or more vault folders)
- `--vault name:path` args register vaults into the Vault instance
- creates the mcp and/or api servers that wrap the vault's obsidian request tool
- important: the web routes are not included in the openapi.json for the api (so that they are not interpreted as AI tools)

**publish.py**
Runs pre-deploy checks and gives the option to publish to pypi.
- pre-deploy checks:
	- local version > than published
	- changelog: does not have a **`## Unreleased`** and does have a **`##`** section matching local version; deploy requires a version section (rename Unreleased when publishing). Use Unreleased only when there is unreleased work—omit it when the tree matches the last release.
	- all tests pass
	- runs update_screenshots.py
	- local changes are committed to git (optional `--skip-git-clean` for `--check` only)
	- pypi token in env vars or passed in as an arg (optional `--skip-pypi-token` for `--check` only; deploy always needs a token)
- deploy:
	- rebuild distributables
	- tag version on latest commit
	- publish to pypi

**update_screenshots.py**
Runs the server with a test vault, sets up some realistic details, and renders the pages as screenshots.
- Screenshots are only updated (file only modified) if the image has changed.
- Browser is screenshotted at 600x600 content area size
- Screenshot List:
	- "home" showing user "admin" showing 3 users and 2 vaults (users: "admin", "friend1", "ai_agent1")
	- "users" showing "admin" (admin) and "friend1" (not admin)
	- "user" showing "friend1" with access:
		- read only access to "work:/Templates"
		- readwrite access to "work:/OurSharedFolder"
	- "vaults" showing "work" (ok) and "personal" (ok)
	- "vault" showing "work" vault details
	- All other pages get screenshots with generic example info, e.g. login, config, etc.

**README.md**
A brief project readme covering:
- A complete Obsidian tool in ~ < x > tokens. (part of previous links to tool_prompt.md)
- what it does
- api reference links (redocly & swagger to the openapi.json)
- whats good about it, take inspiration from:
	- "Maximum Control"
		- Works for any form of text files in vault, json, etc
		- AI can do advanced regex searches
		- Limits, Paging, Sort on all requests, AI can adjust snippet sizes on search results
		- Every call is a batch — multiple operations in one round-trip by default saves time and tokens.
		- Create multiple users with their own keys, different read/write permissions and per-vault folder access
		- Multi-vault: serve multiple Obsidian vaults from one server, AI can search and move across vaults
	- "Maximum Flexibility"
		- Access anywhere
			- WebUI for human to manage vaults, users and config
			- MCP http streaming for agents to use
			- OpenAPI api for agents and web-app integrations
		- Run anywhere
			- Locally on PC w/ Obsidian app
			- Headless in container with multi-vault sync
			- With ob sync or just from folder
		- Compatibility Hacks Pre-Applied
			- Is your agent harness --a piece of garbage-- dropping rich parameter schemas? No problem we collapse the request details into the func docstring and take a json string.
	- "Maximum Token Efficiency"
		- Ruthless minimalism
			- Single CLI command
			- Single tool interface for AI
			- AI able to perform all admin work, once AI connects it can take over setup for you
			- Maximally powerful requests to minimize request and param counts
		- Less Tokens = Faster and Cheaper
		- The entire tool schema uses ~ < X > tokens thanks to minimized docstrings, zero duplication or boilerplate (link to tool prompt)
		- Note about ~ 50% savings on MCP tokens after trimming the FastMCP generated schemas
		- Responses that would have repeated keys, e.g. search results, files lists, are flattened into text formats < show the formats > for savings on every result

- quick start
- options
- what it persists and where (central config, not in vault)
- add screenshots where they are most appropriate and relevant
- (use absolute links to the github file browser's latest version of the file for all internal references so they work on pypi too)

**CHANGELOG.md**
A [Keep a Changelog](https://keepachangelog.com/)-style log: use **`## Unreleased`** only while there are changes not yet released—accumulate bullets there, and **remove** the Unreleased section when there is nothing pending (do not keep an empty placeholder). Do not add a dated **`## x.y.z`** section until you ship; unreleased work stays under Unreleased only. When cutting a release, rename **`## Unreleased`** to **`## x.y.z`** (matching `pyproject.toml`), bump version if needed, and publish.

**docker-compose.yaml**
Deploys the mini-server on a docker container, exposing the port from the env vars above.
- Base image includes Node.js (for obsidian-headless)
- All config persisted in a `/data` volume — survives container restarts
- No `--vault` args; add vaults via the web UI after first run
- The server handles obs installation, auth and sync internally — no manual scripting needed
