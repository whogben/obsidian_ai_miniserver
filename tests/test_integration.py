"""Integration tests: start real servers and test over HTTP."""

import asyncio
import json
import socket
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import uvicorn

from obs_ai_ms.entry import create_api, create_mcp
from obs_ai_ms.models import PathAccess, User
from obs_ai_ms.vault import Vault


# --- Helpers ---


def _find_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for(port: int, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.05)
    raise RuntimeError(f"Server on port {port} did not start")


# --- Fixtures ---


@pytest.fixture
def vault(tmp_path):
    """Multi-vault Vault with sample files and known users."""
    # Work vault
    work = tmp_path / "work"
    (work / "notes").mkdir(parents=True)
    (work / "notes" / "test.md").write_text("hello world")
    (work / "readme.md").write_text("readme content")
    (work / ".obsidian").mkdir()
    (work / ".obsidian" / "daily-notes.json").write_text('{"folder":"Dailies"}')

    # Personal vault
    personal = tmp_path / "personal"
    (personal / "journal").mkdir(parents=True)
    (personal / "journal" / "day1.md").write_text("dear diary")
    (personal / ".obsidian").mkdir()

    v = Vault(config_path=str(tmp_path / "config.json"))
    v.register_vault("work", str(work))
    v.register_vault("personal", str(personal))
    v.config.users = [
        User(token="admin-token", is_admin=True),
        User(
            username="reader",
            token="reader-token",
            is_admin=False,
            access=[PathAccess(path="work:notes/", read=True, write=False)],
        ),
    ]
    v._save_config()
    return v


@pytest.fixture
def api_server(vault):
    """Start FastAPI on a random port, yield base URL."""
    app = create_api(vault)
    port = _find_port()
    threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": "127.0.0.1", "port": port, "log_level": "error"},
        daemon=True,
    ).start()
    _wait_for(port)
    yield f"http://127.0.0.1:{port}"


@pytest.fixture
def mcp_server(vault):
    """Start combined API+MCP server on a random port, yield MCP base URL."""
    mcp = create_mcp(vault)
    mcp_asgi = mcp.http_app(transport="streamable-http", path="/")

    @asynccontextmanager
    async def lifespan(app):
        async with mcp_asgi.router.lifespan_context(mcp_asgi):
            yield

    api = create_api(vault, lifespan=lifespan)
    api.mount("/mcp", mcp_asgi)

    port = _find_port()
    threading.Thread(
        target=uvicorn.run,
        args=(api,),
        kwargs={"host": "127.0.0.1", "port": port, "log_level": "error"},
        daemon=True,
    ).start()
    _wait_for(port)
    yield f"http://127.0.0.1:{port}/mcp"


# --- FastAPI Integration Tests ---


def test_api_get_vaults_info(api_server):
    resp = httpx.post(
        f"{api_server}/api/obsidian",
        json={"requests": '[{"kind": "get_vault_info"}]'},
        headers={"Authorization": "Bearer admin-token"},
    )
    assert resp.status_code == 200
    data = resp.json()[0]
    assert data["kind"] == "vault_info"
    assert isinstance(data["vaults"], list)
    assert len(data["vaults"]) == 2
    assert data["user"]["username"] == "admin"


def test_api_read_write(api_server):
    # Write
    resp = httpx.post(
        f"{api_server}/api/obsidian",
        json={"requests": '[{"kind": "write_text", "path": "work:new.md", "text": "integration test"}]'},
        headers={"Authorization": "Bearer admin-token"},
    )
    assert resp.status_code == 200
    assert resp.json()[0]["kind"] == "success"

    # Read back
    resp = httpx.post(
        f"{api_server}/api/obsidian",
        json={"requests": '[{"kind": "read_text", "path": "work:new.md"}]'},
        headers={"Authorization": "Bearer admin-token"},
    )
    assert resp.status_code == 200
    data = resp.json()[0]
    assert data["kind"] == "file_text"
    assert data["text"] == "integration test"


def test_api_unauthorized(api_server):
    # Missing token
    resp = httpx.post(
        f"{api_server}/api/obsidian",
        json={"requests": '[{"kind": "get_vault_info"}]'},
    )
    assert resp.status_code == 401

    # Bad token
    resp = httpx.post(
        f"{api_server}/api/obsidian",
        json={"requests": '[{"kind": "get_vault_info"}]'},
        headers={"Authorization": "Bearer bad-token"},
    )
    assert resp.status_code == 401


def test_api_access_denied(api_server):
    # Reader can't read outside allowed path
    resp = httpx.post(
        f"{api_server}/api/obsidian",
        json={"requests": '[{"kind": "read_text", "path": "work:readme.md"}]'},
        headers={"Authorization": "Bearer reader-token"},
    )
    assert resp.status_code == 200
    data = resp.json()[0]
    assert data["kind"] == "error"
    assert "access denied" in data["message"].lower()

    # Reader can't write
    resp = httpx.post(
        f"{api_server}/api/obsidian",
        json={"requests": '[{"kind": "write_text", "path": "work:notes/test.md", "text": "hacked"}]'},
        headers={"Authorization": "Bearer reader-token"},
    )
    assert resp.status_code == 200
    assert resp.json()[0]["kind"] == "error"


# --- MCP Integration Tests ---


def test_mcp_tool_call(mcp_server):
    """Connect to MCP server, call the obsidian tool, verify response."""
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    transport = StreamableHttpTransport(
        url=mcp_server,
        headers={"Authorization": "Bearer admin-token"},
    )

    async def _call():
        async with Client(transport) as client:
            result = await client.call_tool(
                "obsidian",
                {"requests": '[{"kind": "get_vault_info"}]'},
            )
            return result

    result = asyncio.run(_call())
    assert result.content
    text = result.content[0].text
    data = json.loads(text)
    assert data[0]["kind"] == "vault_info"


# --- OpenAPI JSON Sync ---


def test_openapi_json_sync(api_server):
    """Ensure openapi.json at project root matches the live app schema."""
    resp = httpx.get(f"{api_server}/api/openapi.json")
    assert resp.status_code == 200
    live = resp.json()

    # Web routes must not appear in the API schema
    for path in live.get("paths", {}):
        assert not path.startswith("/web/"), f"Web route {path} leaked into API openapi.json"

    root = Path(__file__).resolve().parent.parent / "openapi.json"
    if root.exists():
        stored = json.loads(root.read_text())
        if stored == live:
            return  # already in sync

    root.write_text(json.dumps(live, indent=2) + "\n")


def test_tool_prompt_md():
    """Keep tool_prompt.md in sync with the current tool description."""
    from obs_ai_ms.entry import _tool_description

    prompt = _tool_description()

    root = Path(__file__).resolve().parent.parent
    prompt_path = root / "tool_prompt.md"
    if prompt_path.exists() and prompt_path.read_text() == prompt:
        return  # already in sync
    prompt_path.write_text(prompt)


def test_readme_token_count():
    """The ~X,XXX tokens in README is counted via tiktoken on tool_prompt.md."""
    import re

    import tiktoken

    root = Path(__file__).resolve().parent.parent
    prompt_path = root / "tool_prompt.md"
    assert prompt_path.exists(), "Run test_tool_prompt_md first"

    prompt = prompt_path.read_text()
    tokens = len(tiktoken.encoding_for_model("gpt-4o").encode(prompt))
    expected = f"~{tokens:,} tokens"

    readme_path = root / "README.md"
    readme = readme_path.read_text()
    matches = re.findall(r"~[\d,]+ tokens", readme)
    assert matches, "No token count pattern found in README"

    if expected not in readme:
        readme = re.sub(r"~[\d,]+ tokens", expected, readme)
        readme_path.write_text(readme)


# --- Web UI Integration Tests ---


def test_web_login_page_renders(api_server):
    resp = httpx.get(f"{api_server}/web/login")
    assert resp.status_code == 200
    assert "Login" in resp.text


def test_web_login_success(api_server):
    resp = httpx.post(
        f"{api_server}/web/login",
        data={"access_token": "admin-token"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/web/"
    assert "obs_token" in resp.headers.get("set-cookie", "")


def test_web_login_http_with_https_fqdn(vault, api_server):
    """Secure must not follow fqdn when the browser connects over HTTP."""
    vault.config.fqdn = "https://example.com"
    resp = httpx.post(
        f"{api_server}/web/login",
        data={"access_token": "admin-token"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert "secure" not in set_cookie
    resp = httpx.get(
        f"{api_server}/web/",
        cookies=resp.cookies,
        follow_redirects=False,
    )
    assert resp.status_code == 200


def test_web_login_secure_behind_proxy(vault, api_server):
    vault.config.fqdn = "http://example.com"
    resp = httpx.post(
        f"{api_server}/web/login",
        data={"access_token": "admin-token"},
        headers={"X-Forwarded-Proto": "https"},
        follow_redirects=False,
    )
    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert "secure" in set_cookie


def test_web_login_invalid_token(api_server):
    resp = httpx.post(
        f"{api_server}/web/login",
        data={"access_token": "bad-token"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "Invalid token" in resp.text


def test_web_logout(api_server):
    resp = httpx.post(
        f"{api_server}/web/logout",
        cookies={"obs_token": "admin-token"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/web/login"
    set_cookie = resp.headers.get("set-cookie", "")
    assert "obs_token" in set_cookie
    assert "Max-Age=0" in set_cookie
    assert "path=/web" in set_cookie.lower()


def test_web_unauthenticated_redirect(api_server):
    resp = httpx.get(f"{api_server}/web/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/web/login"


def test_web_home_page(api_server):
    resp = httpx.get(
        f"{api_server}/web/",
        cookies={"obs_token": "admin-token"},
    )
    assert resp.status_code == 200
    assert "work" in resp.text
    assert "personal" in resp.text
    assert "admin" in resp.text


def test_web_config_page(api_server):
    resp = httpx.get(
        f"{api_server}/web/config",
        cookies={"obs_token": "admin-token"},
    )
    assert resp.status_code == 200
    assert "address" in resp.text
    assert "port" in resp.text
    assert "fqdn" in resp.text
    assert "base_path" in resp.text
    assert "Server Config" in resp.text
    # No vault_path in multi-vault config
    assert "vault_path" not in resp.text


def test_web_users_page(api_server):
    resp = httpx.get(
        f"{api_server}/web/users",
        cookies={"obs_token": "admin-token"},
    )
    assert resp.status_code == 200
    assert "reader" in resp.text
    assert "Users" in resp.text


def test_web_add_user(api_server):
    resp = httpx.post(
        f"{api_server}/web/users/add",
        data={"username": "newuser", "access_token": "new-token"},
        cookies={"obs_token": "admin-token"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/web/users"

    # Verify user appears in users list
    resp = httpx.get(
        f"{api_server}/web/users",
        cookies={"obs_token": "admin-token"},
    )
    assert "newuser" in resp.text


def test_web_edit_user(api_server):
    resp = httpx.post(
        f"{api_server}/web/users/reader",
        data={"username": "reader", "access_token": "reader-token", "is_admin": "true"},
        cookies={"obs_token": "admin-token"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/web/users"


def test_web_delete_user(api_server):
    resp = httpx.post(
        f"{api_server}/web/users/reader/delete",
        cookies={"obs_token": "admin-token"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/web/users"

    # Verify user is gone from users list
    resp = httpx.get(
        f"{api_server}/web/users",
        cookies={"obs_token": "admin-token"},
    )
    assert "reader" not in resp.text


def test_web_vaults_page(api_server):
    resp = httpx.get(
        f"{api_server}/web/vaults",
        cookies={"obs_token": "admin-token"},
    )
    assert resp.status_code == 200
    assert "Vaults" in resp.text
    assert "work" in resp.text
    assert "personal" in resp.text


def test_web_add_vault(api_server, tmp_path):
    new_vault = tmp_path / "newvault"
    new_vault.mkdir()
    (new_vault / ".obsidian").mkdir()

    resp = httpx.post(
        f"{api_server}/web/vaults/add",
        data={"name": "newvault", "dir_path": str(new_vault)},
        cookies={"obs_token": "admin-token"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/web/vaults"

    # Verify vault appears in vaults list
    resp = httpx.get(
        f"{api_server}/web/vaults",
        cookies={"obs_token": "admin-token"},
    )
    assert "newvault" in resp.text
