from __future__ import annotations

import secrets
from collections.abc import Callable
from html import escape as _h

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .models import (
    AddUserPage,
    AddVaultPage,
    AdminUpsertUser,
    AdminUpsertVault,
    ConfigPage,
    HomePage,
    LoginPage,
    PathAccess,
    ServerConfig,
    User,
    UserPage,
    UsersPage,
    VaultConfig,
    VaultPage,
    VaultsPage,
)
from .vault import Vault


def parse_access(form) -> list[PathAccess]:
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


class WebRedirect(Exception):
    """Raised by web admin dependency to redirect unauthenticated requests."""

    def __init__(self, url: str):
        self.url = url


def create_web_app(
    vault: Vault,
    config: ServerConfig,
    authenticate: Callable[[str | None], User | None],
) -> FastAPI:
    """Admin HTML UI mounted at /web (routes are relative to mount)."""
    web = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @web.exception_handler(WebRedirect)
    async def _redirect_handler(request, exc: WebRedirect):
        return RedirectResponse(exc.url, status_code=303)

    def _web_user(
        obs_token: str | None = Cookie(default=None),
    ) -> User:
        if not obs_token:
            raise WebRedirect(f"{config.base_path}/web/login")
        user = authenticate(obs_token)
        if not user:
            raise WebRedirect(f"{config.base_path}/web/login")
        if not user.is_admin:
            raise HTTPException(status_code=403, detail="Admin access required")
        return user

    @web.get("/login", response_class=HTMLResponse)
    def web_login(request: Request):
        if authenticate(request.cookies.get("obs_token")):
            return RedirectResponse(f"{config.base_path}/web/", status_code=303)
        return HTMLResponse(render_login(LoginPage(), base_path=config.base_path))

    @web.post("/login")
    async def web_login_post(request: Request):
        form = await request.form()
        access_token = form.get("access_token", "")
        user = vault.authenticate(access_token) if access_token else None
        if not user:
            return HTMLResponse(render_login(LoginPage(login_error="Invalid token"), base_path=config.base_path))
        resp = RedirectResponse(f"{config.base_path}/web/", status_code=303)
        resp.set_cookie(
            "obs_token",
            access_token,
            httponly=True,
            samesite="strict",
            path="/web",
            secure=config.fqdn.startswith("https"),
        )
        return resp

    @web.post("/logout")
    def web_logout():
        resp = RedirectResponse(f"{config.base_path}/web/login", status_code=303)
        resp.delete_cookie("obs_token", path="/web")
        return resp

    @web.get("/", response_class=HTMLResponse)
    def web_home(user: User = Depends(_web_user)):
        fqdn = config.fqdn or f"http://{config.address}:{config.port}"
        bp = config.base_path
        # Compute live status for each vault
        vaults = [v.model_copy(update={"status": vault._compute_status(v)}) for v in config.vaults]
        return HTMLResponse(
            render_home(
                HomePage(
                    vaults=vaults,
                    username=user.username,
                    web_fqdn=f"{fqdn}{bp}/web",
                    api_fqdn=f"{fqdn}{bp}/api",
                    mcp_fqdn=f"{fqdn}{bp}/mcp",
                ),
                base_path=config.base_path,
            )
        )

    @web.get("/config", response_class=HTMLResponse)
    def web_config(request: Request, user: User = Depends(_web_user)):
        page_config = config.model_copy(update={
            "users": list(vault.users),
            "obs_password": "••••••" if config.obs_password else "",
        })
        has_sync_vaults = any(v.dir_path.startswith("sync:") for v in config.vaults)
        sync_log = []
        sync_active = False
        if vault.sync_manager:
            sync_active = vault.sync_manager.is_active
            sync_log = vault.sync_manager.get_recent_log(50)
        elif has_sync_vaults:
            sync_active = False
            if config.obs_username:
                sync_log = ["Sync configured but not running — check server logs"]
            else:
                sync_log = ["Sync vaults configured but Obsidian credentials not set — add them above"]
        autorefresh = request.query_params.get("autorefresh") == "1"
        return HTMLResponse(render_config(
            ConfigPage(config=page_config, sync_log=sync_log, sync_active=sync_active),
            base_path=config.base_path,
            autorefresh=autorefresh,
        ))

    @web.post("/config")
    async def web_config_save(request: Request, auth_user: User = Depends(_web_user)):
        form = await request.form()
        new_user = form.get("obs_username", "")
        new_pass = form.get("obs_password", "")
        if new_pass == "••••••":
            new_pass = config.obs_password
        config.obs_username = new_user
        config.obs_password = new_pass
        vault._save_config()
        vault.ensure_sync_manager()
        return RedirectResponse(f"{config.base_path}/web/config", status_code=303)

    # -- User routes --

    @web.get("/users", response_class=HTMLResponse)
    def web_users(user: User = Depends(_web_user)):
        return HTMLResponse(render_users(UsersPage(users=vault.users), base_path=config.base_path))

    @web.get("/users/add", response_class=HTMLResponse)
    def web_user_add_form(user: User = Depends(_web_user)):
        autogenerated_token = secrets.token_urlsafe(16)
        return HTMLResponse(
            render_add_user(
                AddUserPage(autogenerated_token=autogenerated_token, user=User(token=autogenerated_token)),
                User(token=autogenerated_token),
                base_path=config.base_path,
            )
        )

    @web.post("/users/add")
    async def web_user_add_post(request: Request, auth_user: User = Depends(_web_user)):
        form = await request.form()
        vault.obsidian(
            [
                AdminUpsertUser(
                    username=form.get("username", ""),
                    token=form.get("access_token", "") or None,
                    is_admin="is_admin" in form,
                    access=parse_access(form),
                )
            ],
            auth_user,
        )
        return RedirectResponse(f"{config.base_path}/web/users", status_code=303)

    @web.get("/users/{username}", response_class=HTMLResponse)
    def web_user_page(username: str, user: User = Depends(_web_user)):
        for i, u in enumerate(vault.users):
            if u.username == username:
                return HTMLResponse(render_user(UserPage(user=u), u, i, base_path=config.base_path))
        return RedirectResponse(f"{config.base_path}/web/users", status_code=303)

    @web.post("/users/{username}")
    async def web_user_save(request: Request, username: str, auth_user: User = Depends(_web_user)):
        form = await request.form()

        # Re-render with modified access list (no save)
        if "add_access" in form or "delete_access" in form:
            form_user = User(
                username=form.get("username", username),
                token="",
                is_admin="is_admin" in form,
                access=parse_access(form),
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
            return HTMLResponse(render_user(UserPage(user=form_user), form_user, user_idx, base_path=config.base_path))

        vault.obsidian(
            [
                AdminUpsertUser(
                    username=form.get("username", username),
                    token=form.get("access_token", "") or None,
                    is_admin="is_admin" in form,
                    access=parse_access(form),
                )
            ],
            auth_user,
        )
        return RedirectResponse(f"{config.base_path}/web/users", status_code=303)

    @web.post("/users/{username}/delete")
    def web_user_delete(username: str, auth_user: User = Depends(_web_user)):
        vault.obsidian([AdminUpsertUser(username=username, delete=True)], auth_user)
        return RedirectResponse(f"{config.base_path}/web/users", status_code=303)

    # -- Vault routes --

    @web.get("/vaults", response_class=HTMLResponse)
    def web_vaults(user: User = Depends(_web_user)):
        vaults = [v.model_copy(update={"status": vault._compute_status(v)}) for v in config.vaults]
        return HTMLResponse(render_vaults(VaultsPage(vaults=vaults), base_path=config.base_path))

    @web.get("/vaults/add", response_class=HTMLResponse)
    def web_vault_add_form(user: User = Depends(_web_user)):
        return HTMLResponse(render_add_vault(AddVaultPage(vault=VaultConfig(name="", dir_path="")), base_path=config.base_path))

    @web.post("/vaults/add")
    async def web_vault_add_post(request: Request, auth_user: User = Depends(_web_user)):
        form = await request.form()
        vault.obsidian(
            [AdminUpsertVault(name=form.get("name", ""), dir_path=form.get("dir_path", ""))],
            auth_user,
        )
        return RedirectResponse(f"{config.base_path}/web/vaults", status_code=303)

    @web.get("/vaults/{vault_name}", response_class=HTMLResponse)
    def web_vault_page(vault_name: str, user: User = Depends(_web_user)):
        for vc in config.vaults:
            if vc.name == vault_name:
                vc = vc.model_copy(update={"status": vault._compute_status(vc)})
                return HTMLResponse(render_vault(VaultPage(vault=vc), base_path=config.base_path))
        return RedirectResponse(f"{config.base_path}/web/vaults", status_code=303)

    @web.post("/vaults/{vault_name}")
    async def web_vault_save(request: Request, vault_name: str, auth_user: User = Depends(_web_user)):
        form = await request.form()
        new_name = form.get("name", vault_name)
        if new_name != vault_name:
            # Create new first, then delete old (atomic-ish)
            vault.obsidian(
                [AdminUpsertVault(name=new_name, dir_path=form.get("dir_path", ""))],
                auth_user,
            )
            vault.obsidian([AdminUpsertVault(name=vault_name, dir_path="", delete=True)], auth_user)
        else:
            vault.obsidian(
                [AdminUpsertVault(name=new_name, dir_path=form.get("dir_path", ""))],
                auth_user,
            )
        return RedirectResponse(f"{config.base_path}/web/vaults", status_code=303)

    @web.post("/vaults/{vault_name}/delete")
    def web_vault_delete(vault_name: str, auth_user: User = Depends(_web_user)):
        vault.obsidian([AdminUpsertVault(name=vault_name, dir_path="", delete=True)], auth_user)
        return RedirectResponse(f"{config.base_path}/web/vaults", status_code=303)

    return web


def _layout(title: str, body: str, username: str | None = None, base_path: str = "") -> str:
    bp = _h(base_path)
    nav = ""
    if username:
        nav = (
            f'<a href="{bp}/web/">Home</a> '
            f'<a href="{bp}/web/config">Config</a> '
            f'<a href="{bp}/web/users">Users</a> '
            f'<a href="{bp}/web/vaults">Vaults</a> '
            f'<span style="float:right"><b>{_h(username)}</b> '
            f'<form method="post" action="{bp}/web/logout" style="display:inline">'
            f'<button type="submit">Logout</button></form></span>'
        )
    else:
        nav = f'<a href="{bp}/web/login">Login</a>'
    return f"""<!DOCTYPE html>
<html><head><title>{_h(title)}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:720px;margin:2em auto;padding:0 1em;background:#2b2b2b;color:#e0e0e0}}
nav{{border-bottom:1px solid #555;padding:.5em 0;margin-bottom:1.5em}}
a{{margin-right:1em;color:#ccc}}
input[type=text],input[type=password]{{width:100%;box-sizing:border-box;padding:.3em;background:#3a3a3a;color:#e0e0e0;border:1px solid #555}}
table{{border-collapse:collapse;width:100%}}
th,td{{text-align:left;padding:.3em .5em;border-bottom:1px solid #555}}
button,input[type=submit]{{padding:.3em .8em;cursor:pointer;background:#444;color:#e0e0e0;border:1px solid #555}}
.error{{color:#f88}}
.hint{{color:#888;font-size:.85em}}
</style></head><body>
<nav>{nav}</nav>
<h1>{_h(title)}</h1>
{body}
</body></html>"""


def render_login(page: LoginPage, base_path: str = "") -> str:
    bp = _h(base_path)
    error = f'<p class="error">{_h(page.login_error)}</p>' if page.login_error else ""
    body = f"""{error}
<form method="post" action="{bp}/web/login">
<p><label>Access Token<br><input type="password" name="access_token" autofocus></label></p>
<p><button type="submit">Login</button></p>
</form>"""
    return _layout("Login", body, base_path=base_path)


def render_home(page: HomePage, base_path: str = "") -> str:
    bp = _h(base_path)
    error = f'<p class="error">{_h(page.server_error)}</p>' if page.server_error else ""
    vault_rows = ""
    for v in page.vaults:
        vault_rows += f'<tr><td><a href="{bp}/web/vaults/{_h(v.name)}">{_h(v.name)}</a></td><td>{_h(v.status)}</td></tr>\n'
    body = f"""{error}
<table>
<tr><th>Vault</th><th>Status</th></tr>
{vault_rows}</table>
<p>Web: <a href="{_h(page.web_fqdn)}">{_h(page.web_fqdn)}</a></p>
<p>API: <a href="{_h(page.api_fqdn)}">{_h(page.api_fqdn)}</a></p>
<p>MCP: <a href="{_h(page.mcp_fqdn)}">{_h(page.mcp_fqdn)}</a></p>
<p>User: <a href="{bp}/web/users/{_h(page.username)}">{_h(page.username)}</a></p>
<p class="hint">Authenticate via <code>Authorization: Bearer <token></code> header.</p>"""
    return _layout("Obsidian AI Mini Server", body, page.username, base_path)


def render_config(page: ConfigPage, base_path: str = "", autorefresh: bool = False) -> str:
    bp = _h(base_path)
    c = page.config
    body = f"""<table>
<tr><td>address</td><td>{_h(c.address)}</td></tr>
<tr><td>port</td><td>{c.port}</td></tr>
<tr><td>fqdn</td><td>{_h(c.fqdn)}</td></tr>
<tr><td>base_path</td><td>{_h(c.base_path)}</td></tr>
</table>
<form method="post" action="{bp}/web/config">
<p><label>Obs Username<br><input type="text" name="obs_username" value="{_h(c.obs_username)}"></label></p>
<p><label>Obs Password<br><input type="password" name="obs_password" value="{_h(c.obs_password)}"></label>
<span class="hint"> Leave unchanged to keep current</span></p>
<p><button type="submit">Save</button></p>
</form>
<p><a href="{bp}/web/vaults">{len(c.vaults)} Vaults</a> · <a href="{bp}/web/users">{len(c.users)} Users</a></p>"""
    if page.sync_active:
        log_text = _h("\n".join(page.sync_log))
        chk = " checked" if autorefresh else ""
        body += f"""
<h2>Obsidian Sync Log</h2>
<pre style="max-height:300px;overflow:auto;background:#1e1e1e;padding:.5em">{log_text}</pre>
<p><label><input type="checkbox" id="ar"{chk} onchange="location.href=this.checked?'?autorefresh=1':'.'"> Auto-refresh (1s)</label></p>"""
        if autorefresh:
            body += "<script>setTimeout(()=>location.reload(),1000)</script>"
    return _layout("Server Config", body, "admin", base_path)


def render_users(page: UsersPage, base_path: str = "") -> str:
    bp = _h(base_path)
    rows = ""
    for u in page.users:
        admin = " ✓" if u.is_admin else ""
        rows += f'<tr><td><a href="{bp}/web/users/{_h(u.username)}">{_h(u.username)}</a></td><td>{admin}</td></tr>\n'
    body = f"""<table>
<tr><th>Username</th><th>Admin</th></tr>
{rows}</table>
<p><a href="{bp}/web/users/add">Add User</a></p>"""
    return _layout("Users", body, "admin", base_path)


def _user_form(user: User, action: str, is_new: bool, user_index: int) -> str:
    admin_ck = "checked" if user.is_admin else ""
    hint_text = "Copy or overwrite the autogenerated token." if is_new else "Copy before changing. Clear to keep current token."

    access_rows = ""
    for i, ac in enumerate(user.access):
        rec_ck = "checked" if ac.recursive else ""
        rd_ck = "checked" if ac.read else ""
        wr_ck = "checked" if ac.write else ""
        access_rows += f"""<tr>
<td><input type="text" name="access_path" value="{_h(ac.path)}"></td>
<td><input type="checkbox" name="access_recursive" {rec_ck}></td>
<td><input type="checkbox" name="access_read" {rd_ck}></td>
<td><input type="checkbox" name="access_write" {wr_ck}></td>
<td><button type="submit" name="delete_access" value="{i}" onclick="return confirm('Delete this access rule?')">Delete</button></td>
</tr>\n"""

    delete_btn = ""
    if not is_new and user_index != 0:
        delete_btn = (
            f'<form method="post" action="{action}/delete" style="display:inline">'
            f'<button type="submit" onclick="return confirm(\'Delete this user?\')">Delete User</button>'
            f'</form>'
        )

    body = f"""<form method="post" action="{action}">
<p><label>Username<br><input type="text" name="username" value="{_h(user.username)}"></label></p>
<p><label>Access Token<br>
<input type="password" name="access_token" id="tok" value="{_h(user.token)}">
<button type="button" onclick="var t=document.getElementById('tok');t.type=t.type==='password'?'text':'password'">Show</button>
<button type="button" onclick="navigator.clipboard.writeText(document.getElementById('tok').value)">Copy</button>
</label><span class="hint"> {hint_text}</span></p>
<p><label><input type="checkbox" name="is_admin" {admin_ck}> Admin</label></p>
<h2>Access</h2>
<table>
<tr><th>Path</th><th>Recursive</th><th>Read</th><th>Write</th><th></th></tr>
{access_rows}</table>
<p><button type="submit" name="add_access" value="1">Add Access</button></p>
<p>
<button type="submit" name="save" value="1">Save Changes</button>
</p>
</form>
{delete_btn}"""
    return body


def render_user(page: UserPage, user: User, user_index: int, base_path: str = "") -> str:
    bp = _h(base_path)
    body = _user_form(user, f"{bp}/web/users/{_h(user.username)}", False, user_index)
    return _layout(f"User: {user.username}", body, "admin", base_path)


def render_add_user(page: AddUserPage, user: User, base_path: str = "") -> str:
    bp = _h(base_path)
    body = _user_form(user, f"{bp}/web/users/add", True, -1)
    return _layout("Add User", body, "admin", base_path)


# -- Vault renderers --


def render_vaults(page: VaultsPage, base_path: str = "") -> str:
    bp = _h(base_path)
    rows = ""
    for v in page.vaults:
        rows += f'<tr><td><a href="{bp}/web/vaults/{_h(v.name)}">{_h(v.name)}</a></td><td>{_h(v.status)}</td></tr>\n'
    body = f"""<table>
<tr><th>Vault</th><th>Status</th></tr>
{rows}</table>
<p><a href="{bp}/web/vaults/add">Add Vault</a></p>"""
    return _layout("Vaults", body, "admin", base_path)


def _vault_form(vc: VaultConfig, action: str, is_new: bool) -> str:
    status_label = f"<p>Status: {_h(vc.status)}</p>" if vc.status else ""
    daily_label = f"<p>Daily Notes at: {_h(vc.daily_notes_folder)}</p>" if vc.daily_notes_folder else ""
    delete_btn = ""
    if not is_new:
        delete_btn = (
            f'<form method="post" action="{action}/delete" style="display:inline">'
            f'<button type="submit" onclick="return confirm(\'Delete this vault?\')">Delete Vault</button>'
            f'</form>'
        )
    body = f"""<form method="post" action="{action}">
<p><label>Name<br><input type="text" name="name" value="{_h(vc.name)}"></label></p>
<p><label>Directory Path<br><input type="text" name="dir_path" value="{_h(vc.dir_path)}"></label><br><small>Prefix with sync: to auto-sync — final dir name must match the vault name on Obsidian, e.g. sync:/vaults/MyNotes</small></p>
{status_label}{daily_label}
<p>
<button type="submit" name="save" value="1">Save Changes</button>
</p>
</form>
{delete_btn}"""
    return body


def render_vault(page: VaultPage, base_path: str = "") -> str:
    bp = _h(base_path)
    body = _vault_form(page.vault, f"{bp}/web/vaults/{_h(page.vault.name)}", False)
    return _layout(f"Vault: {page.vault.name}", body, "admin", base_path)


def render_add_vault(page: AddVaultPage, base_path: str = "") -> str:
    bp = _h(base_path)
    body = _vault_form(page.vault, f"{bp}/web/vaults/add", True)
    return _layout("Add Vault", body, "admin", base_path)
