from __future__ import annotations

import asyncio
import json
import warnings
from pathlib import Path

import typer
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request

from pydantic import TypeAdapter

from .models import Error, ServerRequest, ServerResponse
from .vault import Vault

app = typer.Typer()


@app.callback()
def _root():
    pass


def _extract_token(auth_header: str | None) -> str | None:
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


def _authenticate(vault: Vault, token: str | None):
    # If admin has no token configured, allow unauthenticated access
    if not vault.users[0].token:
        return vault.users[0]
    if not token:
        return None
    return vault.authenticate(token)


# --- FastAPI ---

_bearer = HTTPBearer(auto_error=False)


def create_api(vault: Vault) -> FastAPI:
    api = FastAPI(
        title="Obsidian AI Mini Server",
        description="REST API for accessing an Obsidian vault. Supports reading, writing, listing files, and user management.",
        version="0.1.0",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
    )

    _DESC = (
        "Access the Obsidian vault. The request body is a JSON object with a **kind** "
        "field that determines the operation and its parameters:\n\n"
        "- **get_vault_info** — `{\"kind\":\"get_vault_info\"}` — Returns vault name, daily-notes folder, and user info.\n"
        "- **read_text** — `{\"kind\":\"read_text\",\"path\":\"...\",\"offset\":0,\"limit\":20000}` — Read file content. `limit: -1` for unlimited.\n"
        "- **write_text** — `{\"kind\":\"write_text\",\"path\":\"...\",\"text\":\"...\"}` — Overwrite file with text.\n"
        "- **append_text** — `{\"kind\":\"append_text\",\"path\":\"...\",\"text\":\"...\"}` — Append text to file.\n"
        "- **replace_text** — `{\"kind\":\"replace_text\",\"path\":\"...\",\"old_text\":\"...\",\"new_text\":\"...\",\"count\":1}` — Replace text. `count: -1` for all occurrences.\n"
        "- **move_file** — `{\"kind\":\"move_file\",\"old_path\":\"...\",\"new_path\":\"...\",\"make_copy\":false}` — Move, copy, or delete a file. Set `new_path: \"\"` to delete.\n"
        "- **list_files** — `{\"kind\":\"list_files\",\"path\":\"\",\"extensions\":[\".md\"],\"max_depth\":1,\"offset\":0,\"limit\":100,\"sort_by\":\"name\",\"sort_order\":\"asc\"}` — List files and folders. `max_depth: -1` or `limit: -1` for unlimited.\n"
        "- **list_users** — `{\"kind\":\"list_users\"}` — List all users (admin only).\n"
        "- **upsert_user** — `{\"kind\":\"upsert_user\",\"username\":\"...\",\"token\":null,\"access\":null,\"is_admin\":null,\"delete_user\":null}` — Create, update, or delete a user (admin only).\n"
    )

    @api.post(
        "/api/obsidian",
        response_model=ServerResponse,
        summary="Obsidian Vault Tool",
        description=_DESC,
    )
    def obsidian(
        request: str = Query(..., description=_DESC),
        credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    ) -> ServerResponse:
        parsed = TypeAdapter(ServerRequest).validate_json(request)
        token = credentials.credentials if credentials else None
        user = _authenticate(vault, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return vault.obsidian(parsed, user)

    return api


# --- FastMCP ---


def _server_request_schema() -> dict:
    """Generate the JSON Schema for ServerRequest (the full discriminated union)."""
    return TypeAdapter(ServerRequest).json_schema()


def create_mcp(vault: Vault) -> FastMCP:
    mcp = FastMCP("obsidian-ai-miniserver")

    @mcp.tool()
    def obsidian(request: str) -> str:
        """Access the Obsidian vault.

        Accepts a request with a 'kind' field that determines the operation.
        Supported kinds: get_vault_info, read_text, write_text, append_text,
        replace_text, move_file, list_files, list_users, upsert_user.
        """
        parsed = TypeAdapter(ServerRequest).validate_json(request)
        try:
            auth = get_http_request().headers.get("authorization", "")
        except RuntimeError:
            auth = ""
        token = _extract_token(auth)
        user = _authenticate(vault, token)
        if not user:
            return Error(message="Invalid token").model_dump_json()
        result = vault.obsidian(parsed, user)
        return result.model_dump_json()

    # FastMCP internal: tested with fastmcp>=2.0 — schema override for MCP client discovery.
    # If this lookup fails (e.g. after a FastMCP upgrade), MCP clients see a plain string schema.
    tool = mcp._local_provider._components.get("tool:obsidian@")
    if tool:
        tool.parameters = {
            "type": "object",
            "properties": {"request": _server_request_schema()},
            "required": ["request"],
        }
    else:
        warnings.warn(
            "Could not override MCP tool schema — tool 'obsidian' not found. "
            "MCP clients will see a plain string schema.",
            stacklevel=2,
        )

    return mcp


# --- CLI ---

@app.command()
def start(
    vault_path: str = typer.Argument(".", help="Path to the Obsidian vault (defaults to current directory)"),
    admin_token: str = typer.Option("", envvar="OBS_AI_MS_ADMIN_TOKEN", help="Admin user token"),
    host: str = typer.Option("127.0.0.1", help="Host to bind to"),
    openapi_port: int = typer.Option(8747, help="OpenAPI port (-1 to disable)"),
    mcp_port: int = typer.Option(8716, help="MCP port (-1 to disable)"),
):
    """Start the Obsidian AI Mini Server."""
    resolved = Path(vault_path).expanduser().resolve()
    if not resolved.is_dir():
        typer.echo(f"Error: Vault path does not exist: {resolved}")
        raise typer.Exit(1)
    vault = Vault(str(resolved))
    if admin_token:
        vault.users[0].token = admin_token
        vault._save_config()

    tasks = []

    if openapi_port != -1:
        api = create_api(vault)
        config = uvicorn.Config(api, host=host, port=openapi_port)
        tasks.append(uvicorn.Server(config).serve())

    if mcp_port != -1:
        mcp = create_mcp(vault)
        tasks.append(mcp.run_async(transport="streamable-http", host=host, port=mcp_port, show_banner=False))

    if not tasks:
        typer.echo("No servers enabled. Set openapi_port or mcp_port to a valid port.")
        raise typer.Exit(1)

    async def _run():
        await asyncio.gather(*tasks)

    asyncio.run(_run())


if __name__ == "__main__":
    app()
