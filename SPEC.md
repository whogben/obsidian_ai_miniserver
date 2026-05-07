
## Design

**Goals**
- Make my Obsidian vault accessible via multiple AI-friendly interfaces:
	- `/api` for OpenAPI (`/api/openapi.json`)
	- `/web` for Web UI
	- `/mcp` for MCP server (streamable HTTP)
- Enable AI to easily find, read and edit text notes.
- Allow for multiple users with limited access, identified by token sent in `Authorization: Bearer` headers.

**Setup**
- Installable via pip `pip install obsidian-ai-miniserver`
- Runnable with command `obs_ai_ms start "your/vault/path" <any optional args>`
	- Required Arg:
		- `your/vault/path` (positional, required) — path to the Obsidian vault
	- Optional Args:
		- `--admin-token` — sets user 0's token
		- `--port` — server port (default `8747`)
		- `--host` — host to bind to (default `127.0.0.1`)
		- `--fqdn` — public URL of this server so it can generate links to itself, e.g. `https://yourdomain.com`
		- `--base-path` — base path when behind a reverse proxy
		- Each option can also be set via an env var: `OBS_AI_MS_` plus the SCREAMING_SNAKE form of the flag name, e.g. `OBS_AI_MS_ADMIN_TOKEN`, `OBS_AI_MS_PORT`, `OBS_AI_MS_BASE_PATH`.

**Use**
- Connect your AI to the MCP or the Open API tool server.
- It can now make requests via the obsidian tool
- Visit `127.0.0.1:<port>/web` for a GUI admin interface for status and user management.

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
	- update_screenshots.py
- docs/
	- images/
		screenshot_< name >.png
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
- Web pages return some of the expected information.
- Committed screenshots under `docs/images/` match the web UI produced by `update_screenshots.py` for the scripted test vault (regenerate that script when `/web` pages change materially)

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
- Able to render pages from the BasePage descendant models.
- Minimal CSS style based on dark-gray thats acceptable for users of dark modes


**persistence**
Config data is persisted inside the vault at .obsidian/obsidian_ai_miniserver.json

**entry.py**
Run by the CLI command to start the combined server with OpenAPI, Streamable HTTP MCP, and the Web UI
- creates a shared vault instance
- creates the mcp and/or api servers that wrap the vault’s obsidian request tool

**publish.py**
Runs pre-deploy checks and gives the option to publish to pypi.
- pre-deploy checks:
	- local version > than published
	- changelog has entry for local version
	- all tests pass
	- runs update_screenshots.py
	- local changes are committed to git
	- pypi token in env vars or passed in as an arg
- deploy:
	- rebuild distributables
	- tag version on latest commit
	- publish to pypi

**update_screenshots.py**
Runs the server with a test vault, sets up some realistic details, and renders the pages as screenshots.
- Screenshots are only updated (file only modified) if the image has changed.
- Browser is screenshotted at 600x600 content area size
- Screenshot List:
	- "home" showing user "admin" showing 3 users
	- "users" showing "admin" (admin) and "friend1" (not admin)
	- "user" showing "friend1" with access:
		- read only access to "/Templates"
		- readwrite access to "/OurSharedFolder"
	- All other pages get screenshots with generic example info, e.g. login, config, etc.

**README.md**
A brief project readme covering:
- what it does
- whats good about it, including
	- Access anywhere
		- WebUI for human to manage
		- MCP http streaming for agents to use
		- OpenAPI api for agents and web-app integrations
	- Control Access
		- Create multiple users with their own keys, different read/write permissions and folder access
		- Keep your personal vault, personal - while enabling agents access to specific subsets
	- Highly Flexible
		- Works for any form of text files in vault, json, etc
		- AI can do advanced regex searches
	- Run anywhere
		- Locally on PC w/ Obsidian app
		- Headless in container
			- With ob sync or just from folder
	- Ruthless minimalism
		- Single CLI command
		- Single tool interface for AI
		- AI able to perform all admin work, once AI connects it can take over setup for you
	- Less tokens = less cost, faster
		- Maximally powerful requests to minimize request and param counts
		- Batch request
		- Limits, Paging, Sort on all requests, AI can adjust snippet sizes on search results, etc
		- Minimized docstrings, zero duplication or boilerplate
- quick start
- options
- what it persists in the vault and where
- local link to openapi file for detailed definitions
- mix in the home, users and user screenshots ensuring at least one is above the fold
	- use absolute raw github links so the images show on pypi too

**CHANGELOG.md**
A standard change log with an entry corresponding to each released version.

**docker-compose.yaml**
Deploys the mini-server on a docker container with the obsidian sync CLI "ob", exposing the port from the env vars above.
- Expects ENV vars:
	- OBSIDIAN_USERNAME
	- OBSIDIAN_PASSWORD
	- OBSIDIAN_VAULTNAME
	- All the OBS_A_MS ENV vars that the server can accept can be passed through
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
