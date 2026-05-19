from __future__ import annotations

import json
import warnings
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from typing import get_args

import typer
import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request

from pydantic import TypeAdapter

from .models import Error, ObsidianBody, ServerConfig, ServerRequest, ServerResponse, TOOL_PROMPT
from .sync import SyncManager
from .vault import Vault
from .webui import create_web_app

app = typer.Typer()


@app.callback()
def _root():
    pass


def _extract_token(auth_header: str | None) -> str | None:
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


def _authenticate(vault: Vault, token: str | None):
    if not token:
        return None
    return vault.authenticate(token)


# --- Schema Description ---


def _format_default(val) -> str:
    if val is None:
        return "None"
    if isinstance(val, bool):
        return str(val).lower()
    if isinstance(val, str):
        return f'"{val}"'
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        return json.dumps(val)
    return repr(val)


def _format_param(name: str, prop: dict, is_required: bool) -> str:
    pieces = [name]
    if not is_required:
        pieces.append(f"={_format_default(prop.get('default'))}")
    enum = prop.get("enum")
    if enum:
        pieces.append(f" [{'|'.join(str(v) for v in enum)}]")
    desc = prop.get("description")
    if desc:
        pieces.append(f' "{desc}"')
    return "".join(pieces)


def _schema_description() -> str:
    """Generate compact text describing all request types from JSON schemas."""
    lines = []
    union = get_args(ServerRequest)[0]
    for cls in get_args(union):
        schema = cls.model_json_schema()
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        kind = props["kind"]["const"]
        doc = " ".join(schema.get("description", "").split())
        parts = []
        for name, prop in props.items():
            if name == "kind":
                continue
            parts.append(_format_param(name, prop, name in required))
        sig = f"{kind}({', '.join(parts)})" if parts else kind
        lines.append(f"- {sig}: {doc}")
    return "\n".join(lines)


def _tool_description() -> str:
    """Full tool description used by both API and MCP endpoints."""
    return TOOL_PROMPT.format(request_kinds=_schema_description())


# --- FastAPI ---

_bearer = HTTPBearer(auto_error=False)


def create_api(vault: Vault, config: ServerConfig | None = None, lifespan=None) -> FastAPI:
    if config is None:
        config = vault.config
    try:
        _ver = _pkg_version("obsidian-ai-miniserver")
    except PackageNotFoundError:
        _ver = "0.0.0-dev"
    api = FastAPI(
        title="Obsidian AI Mini Server",
        description="REST API for accessing Obsidian vaults. Supports reading, writing, listing files, and user management.",
        version=_ver,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        lifespan=lifespan,
    )
    api.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @api.post(
        "/api/obsidian",
        summary="Obsidian Vault Tool",
        description=_tool_description(),
    )
    def obsidian(
        body: ObsidianBody,
        credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    ):
        token = credentials.credentials if credentials else None
        user = _authenticate(vault, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        parsed = TypeAdapter(list[ServerRequest]).validate_json(body.requests)
        result = vault.obsidian(parsed, user)
        return Response(
            content=TypeAdapter(list[ServerResponse]).dump_json(
                result, exclude_none=True
            ),
            media_type="application/json",
        )

    # Web UI: sub-app so routes stay out of /api/openapi.json
    api.mount("/web", create_web_app(vault, config, lambda t: _authenticate(vault, t)))
    return api


# --- FastMCP ---


def create_mcp(vault: Vault) -> FastMCP:
    mcp = FastMCP("obsidian-ai-miniserver")

    doc = _tool_description()

    @mcp.tool()
    def obsidian(requests: str) -> str:
        """Access one or more Obsidian vaults."""
        try:
            auth = get_http_request().headers.get("authorization", "")
        except RuntimeError:
            auth = ""
        token = _extract_token(auth)
        user = _authenticate(vault, token)
        if not user:
            return TypeAdapter(list[ServerResponse]).dump_json(
                [Error(message="Invalid token")], exclude_none=True
            ).decode()
        parsed = TypeAdapter(list[ServerRequest]).validate_json(requests)
        result = vault.obsidian(parsed, user)
        return TypeAdapter(list[ServerResponse]).dump_json(
            result, exclude_none=True
        ).decode()

    # Override tool description with full schema text
    tool = mcp._local_provider._components.get("tool:obsidian@")
    if tool:
        tool.description = doc
    else:
        warnings.warn(
            "Could not override MCP tool description — tool 'obsidian' not found.",
            stacklevel=2,
        )

    return mcp


# --- CLI ---

@app.command()
def start(
    vaults: list[str] = typer.Option([], '--vault', help="Vault to register as name:path, repeatable"),
    config: str = typer.Option("", envvar="OBS_AI_MS_CONFIG", help="Path to config file"),
    admin_token: str = typer.Option("", envvar="OBS_AI_MS_ADMIN_TOKEN", help="Admin user token"),
    host: str = typer.Option("127.0.0.1", envvar="OBS_AI_MS_HOST", help="Host to bind to"),
    port: int = typer.Option(8747, envvar="OBS_AI_MS_PORT", help="Server port"),
    fqdn: str = typer.Option("", envvar="OBS_AI_MS_FQDN", help="Public URL of this server"),
    base_path: str = typer.Option("", envvar="OBS_AI_MS_BASE_PATH", help="Base path for reverse proxy"),
    obs_username: str = typer.Option("", envvar="OBS_AI_MS_OBS_USERNAME", help="Obsidian account email for headless sync"),
    obs_password: str = typer.Option("", envvar="OBS_AI_MS_OBS_PASSWORD", help="Obsidian account password for headless sync"),
):
    """Start the Obsidian AI Mini Server."""
    vault = Vault(config_path=config or None)

    # Register --vault name:path args
    for v in vaults:
        if ":" not in v:
            typer.echo(f"Error: --vault format is name:path, got: {v}")
            raise typer.Exit(1)
        name, dir_path = v.split(":", 1)
        vault.register_vault(name, dir_path)

    # Apply admin token override
    if admin_token:
        vault.config.users[0].token = admin_token
        vault._save_config()

    # Apply sync credentials
    if obs_username:
        vault.config.obs_username = obs_username
    if obs_password:
        vault.config.obs_password = obs_password

    # Apply runtime server settings
    vault.config.address = host
    vault.config.port = port
    vault.config.fqdn = fqdn
    vault.config.base_path = base_path

    has_sync = any(v.dir_path.startswith("sync:") for v in vault.config.vaults)
    if has_sync and vault.config.obs_username:
        sync_mgr = SyncManager(vault.config.obs_username, vault.config.obs_password, vault.config.vaults)
        vault.sync_manager = sync_mgr
    else:
        sync_mgr = None

    mcp = create_mcp(vault)
    mcp_asgi = mcp.http_app(transport="streamable-http", path="/")

    @asynccontextmanager
    async def lifespan(app):
        if sync_mgr:
            sync_mgr.start()
        try:
            async with mcp_asgi.router.lifespan_context(mcp_asgi):
                yield
        finally:
            if sync_mgr:
                sync_mgr.stop()

    api = create_api(vault, lifespan=lifespan)
    api.mount("/mcp", mcp_asgi)

    bp = vault.config.base_path
    typer.echo(f"Web UI: http://{host}:{port}{bp}/web/")
    typer.echo(f"API docs: http://{host}:{port}{bp}/api/docs")
    typer.echo(f"MCP: http://{host}:{port}{bp}/mcp/")
    for vc in vault.config.vaults:
        status = vault._compute_status(vc)
        typer.echo(f"  Vault '{vc.name}': {status}")
    uvicorn.run(api, host=host, port=port)


if __name__ == "__main__":
    app()
