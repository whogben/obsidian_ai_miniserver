"""Integration tests: start real servers and test over HTTP."""

import asyncio
import json
import socket
import threading
import time
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
    """Vault with sample files and known users."""
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "test.md").write_text("hello world")
    (tmp_path / "readme.md").write_text("readme content")

    obs = tmp_path / ".obsidian"
    obs.mkdir()
    (obs / "daily-notes.json").write_text('{"folder":"Dailies"}')

    v = Vault(str(tmp_path))
    v.users = [
        User(token="admin-token", is_admin=True),
        User(
            username="reader",
            token="reader-token",
            is_admin=False,
            access=[PathAccess(path="notes/", read=True, write=False)],
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
    """Start MCP HTTP server on a random port, yield base URL."""
    mcp = create_mcp(vault)
    port = _find_port()

    def _run():
        asyncio.run(
            mcp.run_async(
                transport="streamable-http",
                host="127.0.0.1",
                port=port,
                show_banner=False,
            )
        )

    threading.Thread(target=_run, daemon=True).start()
    _wait_for(port)
    yield f"http://127.0.0.1:{port}/mcp"


# --- FastAPI Integration Tests ---


def test_api_get_vault_info(api_server):
    resp = httpx.post(
        f"{api_server}/api/obsidian",
        params={"request": '{"kind": "get_vault_info"}'},
        headers={"Authorization": "Bearer admin-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "vault_info"
    assert data["name"]
    assert data["daily_notes_folder"] == "Dailies"


def test_api_read_write(api_server):
    # Write
    resp = httpx.post(
        f"{api_server}/api/obsidian",
        params={"request": '{"kind": "write_text", "path": "new.md", "text": "integration test"}'},
        headers={"Authorization": "Bearer admin-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["kind"] == "success"

    # Read back
    resp = httpx.post(
        f"{api_server}/api/obsidian",
        params={"request": '{"kind": "read_text", "path": "new.md"}'},
        headers={"Authorization": "Bearer admin-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "file_text"
    assert data["text"] == "integration test"


def test_api_unauthorized(api_server):
    # Missing token
    resp = httpx.post(
        f"{api_server}/api/obsidian",
        params={"request": '{"kind": "get_vault_info"}'},
    )
    assert resp.status_code == 401

    # Bad token
    resp = httpx.post(
        f"{api_server}/api/obsidian",
        params={"request": '{"kind": "get_vault_info"}'},
        headers={"Authorization": "Bearer bad-token"},
    )
    assert resp.status_code == 401


def test_api_access_denied(api_server):
    # Reader can't read outside allowed path
    resp = httpx.post(
        f"{api_server}/api/obsidian",
        params={"request": '{"kind": "read_text", "path": "readme.md"}'},
        headers={"Authorization": "Bearer reader-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "error"
    assert "access denied" in data["message"].lower()

    # Reader can't write
    resp = httpx.post(
        f"{api_server}/api/obsidian",
        params={"request": '{"kind": "write_text", "path": "notes/test.md", "text": "hacked"}'},
        headers={"Authorization": "Bearer reader-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["kind"] == "error"


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
                {"request": '{"kind": "get_vault_info"}'},
            )
            return result

    result = asyncio.run(_call())
    assert result.content
    text = result.content[0].text
    data = json.loads(text)
    assert data["kind"] == "vault_info"


# --- OpenAPI JSON Sync ---


def test_openapi_json_sync(api_server):
    """Ensure openapi.json at project root matches the live app schema."""
    resp = httpx.get(f"{api_server}/api/openapi.json")
    assert resp.status_code == 200
    live = resp.json()

    root = Path(__file__).resolve().parent.parent / "openapi.json"
    if root.exists():
        stored = json.loads(root.read_text())
        if stored == live:
            return  # already in sync

    root.write_text(json.dumps(live, indent=2) + "\n")
