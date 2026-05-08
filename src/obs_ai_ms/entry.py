from __future__ import annotations

import secrets
import warnings
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

import typer
import uvicorn
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_request

from pydantic import TypeAdapter

from .models import (
    AddUserPage,
    AdminUpsertUser,
    ConfigPage,
    Error,
    HomePage,
    LoginPage,
    PathAccess,
    ServerConfig,
    ServerRequest,
    ServerResponse,
    User,
    UserPage,
    UsersPage,
)
from .vault import Vault
from .webui import render_add_user, render_config, render_home, render_login, render_user, render_users

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


def _parse_access(form) -> list[PathAccess]:
    """Parse access rules from form data, grouping by access_path markers."""
    rules: list[PathAccess] = []
    cur: PathAccess | None = None
    for key, val in form.multi_items():
        if key == "access_path":
            if cur is not None:
                rules.append(cur)
            cur = PathAccess(path=val)
        elif cur is not None:
            if key == "access_recursive":
                cur.recursive = True
            elif key == "access_read":
                cur.read = True
            elif key == "access_write":
                cur.write = True
    if cur is not None:
        rules.append(cur)
    return rules


# --- FastAPI ---

_bearer = HTTPBearer(auto_error=False)


def _clean_schemas(schemas: dict[str, dict]):
    """Strip redundant noise from a dict of Pydantic-generated JSON schemas.

    Works for both OpenAPI (components.schemas) and MCP ($defs).
    """
    for schema in schemas.values():
        props = schema.get("properties")
        if not props:
            continue
        for prop in props.values():
            prop.pop("title", None)
            if "const" in prop:
                prop.pop("default", None)
                prop.pop("type", None)
            elif "enum" in prop:
                prop.pop("type", None)
        schema.pop("additionalProperties", None)


def _clean_schema(spec: dict) -> dict:
    """Strip redundant noise from Pydantic-generated OpenAPI schemas."""
    import json

    _clean_schemas(spec.get("components", {}).get("schemas", {}))

    # Deduplicate inline oneOf+discriminator blocks into named schemas
    schemas = spec.get("components", {}).get("schemas", {})

    def _find_oneofs(obj):
        """Yield every inline oneOf+discriminator block."""
        if isinstance(obj, dict):
            if "oneOf" in obj and "discriminator" in obj:
                yield obj
            for v in obj.values():
                yield from _find_oneofs(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from _find_oneofs(v)

    for block in _find_oneofs(spec):
        block["oneOf"].sort(key=lambda r: r.get("$ref", ""))
        block.pop("title", None)

    groups: dict[str, list[dict]] = {}
    for block in _find_oneofs(spec):
        key = json.dumps(block, sort_keys=True)
        groups.setdefault(key, []).append(block)

    for occurrences in groups.values():
        if len(occurrences) < 2:
            continue
        refs = [r["$ref"].rsplit("/", 1)[-1] for r in occurrences[0]["oneOf"]]
        name = f"Union_{'_'.join(sorted(refs))}"
        schemas[name] = occurrences[0].copy()
        for block in occurrences:
            block.clear()
            block["$ref"] = f"#/components/schemas/{name}"

    return spec


class _WebRedirect(Exception):
    """Raised by _web_user dependency to redirect unauthenticated requests."""
    def __init__(self, url: str):
        self.url = url


def create_api(vault: Vault, config: ServerConfig | None = None, lifespan=None) -> FastAPI:
    if config is None:
        config = ServerConfig(vault_path=str(vault.vault_path))
    try:
        _ver = _pkg_version("obsidian-ai-miniserver")
    except PackageNotFoundError:
        _ver = "0.0.0-dev"
    api = FastAPI(
        title="Obsidian AI Mini Server",
        description="REST API for accessing an Obsidian vault. Supports reading, writing, listing files, and user management.",
        version=_ver,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        lifespan=lifespan,
    )

    # Strip redundant noise from the generated schema
    _orig_openapi = api.openapi
    def openapi():
        if api.openapi_schema:
            return api.openapi_schema
        api.openapi_schema = _clean_schema(_orig_openapi())
        return api.openapi_schema
    api.openapi = openapi

    @api.post(
        "/api/obsidian",
        response_model=ServerResponse,
        summary="Obsidian Vault Tool",
    )
    def obsidian(
        request: ServerRequest,
        credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    ) -> ServerResponse:
        token = credentials.credentials if credentials else None
        user = _authenticate(vault, token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return vault.obsidian(request, user)

    # --- Web UI (mounted as sub-app so routes are excluded from /api/openapi.json) ---

    web = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @web.exception_handler(_WebRedirect)
    async def _redirect_handler(request, exc):
        return RedirectResponse(exc.url, status_code=303)

    def _web_user(
        obs_token: str | None = Cookie(default=None),
    ) -> User:
        if not obs_token:
            raise _WebRedirect("/web/login")
        user = _authenticate(vault, obs_token)
        if not user:
            raise _WebRedirect("/web/login")
        if not user.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required")
        return user

    @web.get("/login", response_class=HTMLResponse)
    def web_login(request: Request):
        if _authenticate(vault, request.cookies.get("obs_token")):
            return RedirectResponse("/web/", status_code=303)
        return HTMLResponse(render_login(LoginPage(), base_path=config.base_path))

    @web.post("/login")
    async def web_login_post(request: Request):
        form = await request.form()
        access_token = form.get("access_token", "")
        user = vault.authenticate(access_token) if access_token else None
        if not user:
            return HTMLResponse(render_login(LoginPage(login_error="Invalid token"), base_path=config.base_path))
        resp = RedirectResponse("/web/", status_code=303)
        resp.set_cookie("obs_token", access_token, httponly=True, samesite="strict", path="/web", secure=config.fqdn.startswith("https"))
        return resp

    @web.post("/logout")
    def web_logout():
        resp = RedirectResponse("/web/login", status_code=303)
        resp.delete_cookie("obs_token", path="/web")
        return resp

    @web.get("/", response_class=HTMLResponse)
    def web_home(user: User = Depends(_web_user)):
        fqdn = config.fqdn or f"http://{config.address}:{config.port}"
        bp = config.base_path
        return HTMLResponse(render_home(HomePage(
            vault_name=vault.vault_path.name,
            username=user.username,
            web_fqdn=f"{fqdn}{bp}/web",
            api_fqdn=f"{fqdn}{bp}/api",
            mcp_fqdn=f"{fqdn}{bp}/mcp",
        ), base_path=config.base_path))

    @web.get("/config", response_class=HTMLResponse)
    def web_config(user: User = Depends(_web_user)):
        page_config = config.model_copy(update={"users": list(vault.users)})
        return HTMLResponse(render_config(ConfigPage(config=page_config), base_path=config.base_path))

    @web.get("/users", response_class=HTMLResponse)
    def web_users(user: User = Depends(_web_user)):
        return HTMLResponse(render_users(UsersPage(users=vault.users), base_path=config.base_path))

    @web.get("/users/add", response_class=HTMLResponse)
    def web_user_add_form(user: User = Depends(_web_user)):
        autogenerated_token = secrets.token_urlsafe(16)
        return HTMLResponse(render_add_user(
            AddUserPage(autogenerated_token=autogenerated_token),
            User(token=autogenerated_token),
            base_path=config.base_path,
        ))

    @web.post("/users/add")
    async def web_user_add_post(request: Request, auth_user: User = Depends(_web_user)):
        form = await request.form()
        vault.obsidian(AdminUpsertUser(
            username=form.get("username", ""),
            token=form.get("access_token", "") or None,
            is_admin="is_admin" in form,
            access=_parse_access(form),
        ), auth_user)
        return RedirectResponse("/web/users", status_code=303)

    @web.get("/users/{username}", response_class=HTMLResponse)
    def web_user_page(username: str, user: User = Depends(_web_user)):
        for i, u in enumerate(vault.users):
            if u.username == username:
                return HTMLResponse(render_user(UserPage(), u, i, base_path=config.base_path))
        return RedirectResponse("/web/users", status_code=303)

    @web.post("/users/{username}")
    async def web_user_save(request: Request, username: str, auth_user: User = Depends(_web_user)):
        form = await request.form()

        # Re-render with modified access list (no save)
        if "add_access" in form or "delete_access" in form:
            form_user = User(
                username=form.get("username", username),
                token="",
                is_admin="is_admin" in form,
                access=_parse_access(form),
            )
            if "add_access" in form:
                form_user.access.append(PathAccess())
            elif "delete_access" in form:
                try:
                    idx = int(form.get("delete_access", "-1"))
                except ValueError:
                    idx = -1
                form_user.access = [a for i, a in enumerate(form_user.access) if i != idx]
            user_idx = next((i for i, u in enumerate(vault.users) if u.username == username), -1)
            return HTMLResponse(render_user(UserPage(), form_user, user_idx, base_path=config.base_path))

        vault.obsidian(AdminUpsertUser(
            username=form.get("username", username),
            token=form.get("access_token", "") or None,
            is_admin="is_admin" in form,
            access=_parse_access(form),
        ), auth_user)
        return RedirectResponse("/web/users", status_code=303)

    @web.post("/users/{username}/delete")
    def web_user_delete(username: str, auth_user: User = Depends(_web_user)):
        vault.obsidian(AdminUpsertUser(username=username, delete_user=True), auth_user)
        return RedirectResponse("/web/users", status_code=303)

    api.mount("/web", web)
    return api


# --- FastMCP ---


def _server_request_schema() -> dict:
    """Generate the cleaned JSON Schema for ServerRequest (the full discriminated union)."""
    schema = TypeAdapter(ServerRequest).json_schema()
    _clean_schemas(schema.get("$defs", {}))
    return schema


def create_mcp(vault: Vault) -> FastMCP:
    mcp = FastMCP("obsidian-ai-miniserver")

    @mcp.tool()
    def obsidian(request: str) -> str:
        """Access the Obsidian vault."""
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
    host: str = typer.Option("127.0.0.1", envvar="OBS_AI_MS_HOST", help="Host to bind to"),
    port: int = typer.Option(8747, envvar="OBS_AI_MS_PORT", help="Server port"),
    fqdn: str = typer.Option("", envvar="OBS_AI_MS_FQDN", help="Public URL of this server"),
    base_path: str = typer.Option("", envvar="OBS_AI_MS_BASE_PATH", help="Base path for reverse proxy"),
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

    config = ServerConfig(
        vault_path=str(resolved),
        address=host,
        port=port,
        fqdn=fqdn,
        base_path=base_path,
    )

    mcp = create_mcp(vault)
    mcp_asgi = mcp.http_app(transport="streamable-http", path="/")

    @asynccontextmanager
    async def lifespan(app):
        async with mcp_asgi.router.lifespan_context(mcp_asgi):
            yield

    api = create_api(vault, config, lifespan=lifespan)
    api.mount("/mcp", mcp_asgi)

    bp = config.base_path
    typer.echo(f"Web UI: http://{host}:{port}{bp}/web/")
    typer.echo(f"API docs: http://{host}:{port}{bp}/api/docs")
    uvicorn.run(api, host=host, port=port)


if __name__ == "__main__":
    app()
