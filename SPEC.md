
## Design

**Goals**
- Make my Obsidian vault accessible via REST API and a streamable HTTP MCP server protected by an API key sent in auth headers.
- Enable AI to find, read and edit text notes.

**Setup**
- Installable via pip `pip install obsidian-ai-mini-server`
- Runnable with command `obs_ai_ms start "your/vault/path" <any optional args>`
	- Secure with optional API key `--api_key "your_api_key123`
	- Hosts REST API at `--api_port 8747` by default, set to -1 to disable
	- Hosts MCP over HTTP at `--mcp_port 8716` by default

**Use**
- Connect your AI to the MCP or the Open API tool server.
- It can now make requests via the obsidian tool

**Single Tool Interface**
A single tool (POST) provides all Obsidian vault access, with the caller passing different request objects to it.
- `obsidian( request:Request ) -> Response`
	- `Access the Obsidian vault.`
- Request and Response objects
	- subclass common BaseRequest and BaseResponse
	- `kind` string literal discriminates subclasses
- The request class docstr is the primary per-tool documentation.

----
## Implementation

**Identities**
- Project: github.com/whogben/obsidian_ai_miniserver
- Package: pypi.org/obsidian_ai_miniserver
- Author: William Hogben (willhogben.com)

**Layout**
- SPEC.md (this file)
- src/
	- obs_ai_ms/
		- entry.py <- CLI command runs this
		- models.py <- Defines requests and responses
		- vault.py <- Vault class with the  tool function 
- tests/
	- test_vault/
- scripts/
	- publish.py <- tests, builds, publishes
- pyproject.toml
- README.md
- CHANGELOG.md
- AGENTS.md

**Dependencies**
- fastapi
- fastmcp
- pydantic
- typer

**Tests Validate**
- Each major mode and branch of each requestable and outward facing interface.
- Real connectivity of the mcp and api servers with and without auth.

**SPEC.md**
This human-maintained spec file defines the project as a whole.
- Changes to the spec can cascade or any other part of the project.

**models.py**
This human-maintained schemas file details the project’s inputs and outputs.
- Single source of truth on all of the possible request and response types with all public information about a tool’s inputs and outputs.
- Request implementations are to be derived from this file and updated when this file changes. 

**vault.py**
Defines the main service class, Vault, which:
- accesses a vault folder using cross-platform Python file commands
- ”obsidian” method accepts any single request type and returns any single response type.
- implements all requests

**entry.py**
Run by the CLI command to start the server(s).
- creates a shared vault instance
- creates the mcp and/or api servers that wrap the vault’s obsidian request tool

**publish.py**
Runs pre-deploy checks and gives the option to publish to pypi.
- pre-deploy checks:
	- local version > than published
	- changelog has entry for local version
	- local changes are committed to git
	- pypi token in env vars or passed in as an arg
- deploy:
	- rebuild distributables
	- tag version on latest commit
	- publish to pypi

**README.md**
A brief project readme covering:
- what it does
- quick start
- options

**CHANGELOG.md**
A standard change log with an entry corresponding to each released version.