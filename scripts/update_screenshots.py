#!/usr/bin/env python3
"""Start server with test vault and capture page screenshots."""

import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright

from obs_ai_ms.entry import create_api
from obs_ai_ms.models import PathAccess, ServerConfig, User
from obs_ai_ms.vault import Vault

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
PORT = 8747  # use default port so screenshots match real usage
VAULT_DIR = Path(tempfile.gettempdir()) / "obs_ai_ms_screenshots"

# (name, path) — login first so we capture it before setting auth cookie
SCREENSHOTS = [
    ("login", "/web/login"),
    ("home", "/web/"),
    ("config", "/web/config"),
    ("users", "/web/users"),
    ("user", "/web/users/friend1"),
    ("add_user", "/web/users/add"),
]


def _wait_for(port: int, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.05)
    raise RuntimeError(f"Server on port {port} did not start")


def _make_vault(vault_path: Path) -> Vault:
    """Create test vault with sample files and users."""
    (vault_path / "Templates").mkdir(parents=True)
    (vault_path / "Templates" / "daily.md").write_text("# {{date}}\n\n")
    (vault_path / "OurSharedFolder").mkdir()
    (vault_path / "OurSharedFolder" / "project.md").write_text("# Project Notes\nShared content.")
    (vault_path / "Dailies").mkdir()
    (vault_path / "Dailies" / "2024-01-15.md").write_text("# January 15\nToday's notes.")
    (vault_path / "readme.md").write_text("# My Vault\nWelcome.")

    v = Vault(str(vault_path))
    v.users = [
        User(token="admin-token", is_admin=True),
        User(
            username="friend1",
            token="friend1-token",
            is_admin=False,
            access=[
                PathAccess(path="/Templates", read=True, write=False, recursive=True),
                PathAccess(path="/OurSharedFolder", read=True, write=True, recursive=True),
            ],
        ),
        User(
            username="friend2",
            token="friend2-token",
            is_admin=False,
            access=[PathAccess(path="/", read=True, write=False, recursive=True)],
        ),
    ]
    v._save_config()
    return v


def _screenshot(page, base: str, path: str) -> bytes:
    page.goto(f"{base}{path}")
    page.wait_for_load_state("networkidle")
    return page.screenshot()


def _save(dest: Path, img: bytes, name: str, updated: list, unchanged: list):
    if dest.exists() and dest.read_bytes() == img:
        unchanged.append(name)
    else:
        dest.write_bytes(img)
        updated.append(name)


def main():
    if VAULT_DIR.exists():
        shutil.rmtree(VAULT_DIR)
    vault = _make_vault(VAULT_DIR)

    config = ServerConfig(
        vault_path=str(vault.vault_path),
        address="127.0.0.1",
        port=PORT,
        fqdn=f"http://localhost:{PORT}",
    )
    app = create_api(vault, config)

    threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": "127.0.0.1", "port": PORT, "log_level": "error"},
        daemon=True,
    ).start()
    _wait_for(PORT)

    base = f"http://127.0.0.1:{PORT}"
    OUT.mkdir(parents=True, exist_ok=True)

    updated, unchanged = [], []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 600, "height": 600})

        # Login page — capture before setting auth cookie
        _save(OUT / "screenshot_login.png", _screenshot(page, base, "/web/login"), "login", updated, unchanged)

        # Set auth cookie for remaining pages
        page.context.add_cookies([{
            "name": "obs_token",
            "value": "admin-token",
            "domain": "127.0.0.1",
            "path": "/",
        }])

        for name, path in SCREENSHOTS[1:]:
            _save(OUT / f"screenshot_{name}.png", _screenshot(page, base, path), name, updated, unchanged)

        browser.close()

    print(f"\nScreenshots: {len(updated)} updated, {len(unchanged)} unchanged")
    for name in updated:
        print(f"  ✓ {name}")
    for name in unchanged:
        print(f"  = {name}")


if __name__ == "__main__":
    main()
