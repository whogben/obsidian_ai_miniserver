from __future__ import annotations

import warnings
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

import typer
import uvicorn
from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Request
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

    @api.exception_handler(_WebRedirect)
    async def _redirect_handler(request, exc):
        return RedirectResponse(exc.url, status_code=303)

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

    # --- Web UI ---

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

    @api.get("/web/login", response_class=HTMLResponse)
    def web_login(request: Request):
        if _authenticate(vault, request.cookies.get("obs_token")):
            return RedirectResponse("/web/", status_code=303)
        return HTMLResponse(render_login(LoginPage(), base_path=config.base_path))

    @api.post("/web/login")
    async def web_login_post(request: Request):
        form = await request.form()
        access_token = form.get("access_token", "")
        user = vault.authenticate(access_token) if access_token else None
        if not user:
            return HTMLResponse(render_login(LoginPage(login_error="Invalid token"), base_path=config.base_path))
        resp = RedirectResponse("/web/", status_code=303)
        resp.set_cookie("obs_token", access_token, httponly=True, samesite="strict", path="/web", secure=config.fqdn.startswith("https"))
        return resp

    @api.post("/web/logout")
    def web_logout():
        resp = RedirectResponse("/web/login", status_code=303)
        resp.delete_cookie("obs_token", path="/web")
        return resp

    @api.get("/web/", response_class=HTMLResponse)
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

    @api.get("/web/config", response_class=HTMLResponse)
    def web_config(user: User = Depends(_web_user)):
        page_config = config.model_copy(update={"users": list(vault.users)})
        return HTMLResponse(render_config(ConfigPage(config=page_config), base_path=config.base_path))

    @api.get("/web/users", response_class=HTMLResponse)
    def web_users(user: User = Depends(_web_user)):
        return HTMLResponse(render_users(UsersPage(users=vault.users), base_path=config.base_path))

    @api.get("/web/users/add", response_class=HTMLResponse)
    def web_user_add_form(user: User = Depends(_web_user)):
        return HTMLResponse(render_add_user(AddUserPage(), User(), base_path=config.base_path))

    @api.post("/web/users/add")
    async def web_user_add_post(request: Request, auth_user: User = Depends(_web_user)):
        form = await request.form()
        vault.obsidian(AdminUpsertUser(
            username=form.get("username", ""),
            token=form.get("access_token", "") or None,
            is_admin="is_admin" in form,
            access=_parse_access(form),
        ), auth_user)
        return RedirectResponse("/web/users", status_code=303)

    @api.get("/web/users/{username}", response_class=HTMLResponse)
    def web_user_page(username: str, user: User = Depends(_web_user)):
        for i, u in enumerate(vault.users):
            if u.username == username:
                return HTMLResponse(render_user(UserPage(), u, i, base_path=config.base_path))
        return RedirectResponse("/web/users", status_code=303)

    @api.post("/web/users/{username}")
    async def web_user_save(request: Request, username: str, auth_user: User = Depends(_web_user)):
        form = await request.form()

        # Re-render with modified access list (no save)
        if "add_access" in form or "delete_access" in form:
            form_user = User(
                username=form.get("username", username),
                token=form.get("access_token", ""),
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

    @api.post("/web/users/{username}/delete")
    def web_user_delete(username: str, auth_user: User = Depends(_web_user)):
        vault.obsidian(AdminUpsertUser(username=username, delete_user=True), auth_user)
        return RedirectResponse("/web/users", status_code=303)

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

    uvicorn.run(api, host=host, port=port)


if __name__ == "__main__":
    app()
