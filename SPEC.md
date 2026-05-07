
## Design

**Goals**
- Make my Obsidian vault accessible via REST API and an MCP server.
- Enable AI to easily find, read and edit text notes.
- Allow for multiple users with limited access, identified by token sent in `Authorization: Bearer` headers.

**Setup**
- Installable via pip `pip install obsidian-ai-miniserver`
- Runnable with command `obs_ai_ms start "your/vault/path" <any optional args>`
	- Required Arg:
		- `your/vault/path` (positional, required) — path to the Obsidian vault
	- Optional Args:
		- `--admin_token` — sets user 0's token
		- `--openapi_port 8747` — hosts OpenAPI API, set to -1 to disable
		- `--mcp_port 8716` — hosts MCP over streamable HTTP, set to -1 to disable
		- `--host 127.0.0.1` — host to bind to
		- Each of the optional args can be alternately specified via an env var of the same name prefixed with OBS_AI_MS_ in all caps, e.g. OBS_AI_MS_ADMIN_TOKEN, and so on.

**Use**
- Connect your AI to the MCP or the Open API tool server.
- It can now make requests via the obsidian tool
- Visit `127.0.0.1:<openapi_port>/web` for a GUI admin interface for status and user management.

**Single Tool Interface**
A single function interface accepts different kinds of requests and returns different kinds of responses.
- `obsidian( request:Request ) -> Response`
	- Description: `Access the Obsidian vault.`
    - OpenAPI POST to `/api/obsidian` with query param `request:Request`
    - MCP `obsidian(request:Request) -> Response` tool
- Request and Response objects
	- subclass common BaseRequest and BaseResponse
	- `kind` string literal discriminates subclasses
- The request class docstr is the primary per-tool documentation.

**Run Next to Obsidian**
You can run it on the same computer you run Obsidian on, pointing it at the vault folder.

**Run Headless in Container**
Alternatively, you can run it in a container with just the Obsidian sync service, which is much less RAM and overhead than running full electron-based Obsidian. This is optimal for making Obsidian content available via headless cloud server. 

----
## Implementation

**Identities**
- Project: github.com/whogben/obsidian_ai_miniserver
- Package: pypi.org/obsidian-ai-miniserver
- Author: William Hogben (willhogben.com)

**Layout**
- SPEC.md (this file)
- src/
	- obs_ai_ms/
		- entry.py <- CLI command runs this
		- models.py <- Defines requests, responses, and webui
		- vault.py <- Vault class with the  tool function 
		- webui.py <- All the `/web` interface details
- tests/
	- test_vault.py
	- test_integration.py
- scripts/
	- publish.py <- tests, builds, publishes
- pyproject.toml
- README.md
- openapi.json <- current OpenAPI spec
- CHANGELOG.md
- docker-compose.yaml <- used to deploy headless
- AGENTS.md <- optional extra context for future ai maintainers


**Dependencies**
- fastapi
- fastmcp
- pydantic
- typer
- uvicorn

**Tests Validate**
- Each real interface works, e.g. real CLI test, real HTTP, real MCP
- Each CLI command w/ variation for each optional param
- Each major mode and branch of each requestable and outward facing interface.
- Real connectivity of the mcp and api servers with and without auth.
- Automatically updates the project root's openapi.json if it has changed

**SPEC.md**
This human-maintained spec file defines the project as a whole.
- Changes to the spec can cascade or any other part of the project.

**models.py**
This human-maintained schemas file details the project’s inputs and outputs and web ui elements.
- Single source of truth on all of the possible request and response types with all public information about a tool’s inputs and outputs.
- Request implementations are to be derived from this file and updated when this file changes. 
- Web UI pages are described by models descending BasePage.
- Auth is handled via cookie.

**vault.py**
Defines the main service class, Vault, which:
- accesses a vault folder using cross-platform Python file commands
- ”obsidian” method accepts any single request type and returns any single response type.
- implements all requests
- checks for a .obsidian/daily-notes.json with {"folder":"PathTo/Dailies"} to locate a non-root the daily notes folder.

**webui.py**
Implements the web routes that are defined in models.py, providing all web ui related functionality.
- Returns clean and mininamlist HTML via fstrings.
- Able to render pages from the BasePage and BaseComponent descendant models.

**persistence**
Config data is persisted inside the vault at .obsidian/obsidian_ai_miniserver.json

**entry.py**
Run by the CLI command to start the server(s).
- creates a shared vault instance
- creates the mcp and/or api servers that wrap the vault’s obsidian request tool

**publish.py**
Runs pre-deploy checks and gives the option to publish to pypi.
- pre-deploy checks:
	- local version > than published
	- changelog has entry for local version
	- all tests pass
	- local changes are committed to git
	- pypi token in env vars or passed in as an arg
- deploy:
	- rebuild distributables
	- tag version on latest commit
	- publish to pypi

**README.md**
A brief project readme covering:
- what it does
- whats good about it, including
	- runs without obsidian present / works headless, unlike plugin-based solutions
	- optimized tool signatures and docs to save tokens
	- flexible tools like regex search
	- ability for one ai to admin other ai's access
	- identical mcp and openapi, easy to build integrations against as well as connect ai
- quick start
- options
- what it persists in the vault and where
- local link to openapi file for detailed definitions

**CHANGELOG.md**
A standard change log with an entry corresponding to each released version.

**docker-compose.yaml**
Deploys the mini-server on a docker container with the obsidian sync CLI "ob", exposing the port from the env vars above.
- Expects ENV vars:
	- OBSIDIAN_USERNAME
	- OBSIDIAN_PASSWORD
	- OBSIDIAN_VAULTNAME
	- OBS_AI_MS_OPENAPI_PORT
	- OBS_AI_MS_MCP_PORT
Inside a Python 3.11 slim container:
- On Start
	- install / update to the latest Obsidian Headless CLI via `npm install -g obsidian-headless`
	- authenticates as the provided username and password
	- sync vault into a dir named after it in mounted volume `vaults`
	- install / update to the latest obsidian ai miniserver
	- ensure both obsidian sync cli and ai miniserver are running
- Ongoing
	- maintains syncing with Obsidian servers keeping vault up to date
	- maintains obsidian ai miniserver operating
