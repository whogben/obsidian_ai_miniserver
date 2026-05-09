from __future__ import annotations

import atexit
import logging
import os
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from .models import VaultConfig

log = logging.getLogger(__name__)


class SyncManager:
    """Manages obsidian-headless CLI (`ob`) for sync-managed vaults."""

    def __init__(self, obs_username: str, obs_password: str, vaults: list[VaultConfig]):
        self._username = obs_username
        self._password = obs_password
        self._sync_vaults: list[tuple[str, str]] = []  # (local_path, obs_vault_name)
        for v in vaults:
            if v.dir_path.startswith("sync:"):
                local_path = v.dir_path[len("sync:"):]
                if not local_path:
                    log.warning("Skipping sync vault %r: empty path after sync: prefix", v.name)
                    continue
                obs_vault_name = Path(local_path).name
                self._sync_vaults.append((local_path, obs_vault_name))

        self._log: deque[tuple[float, str, str]] = deque(maxlen=200)
        self._lock = threading.Lock()
        self._processes: dict[str, subprocess.Popen] = {}  # vault_name -> process

    @property
    def sync_vaults(self) -> list[tuple[str, str]]:
        return list(self._sync_vaults)

    def start(self) -> None:
        if not self._sync_vaults:
            return
        if not self._username:
            log.warning("Sync vaults configured but no obs_username set")
            return
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _run(self) -> None:
        """Background thread: install, auth, start sync processes."""
        atexit.register(self.stop)
        try:
            if not self._ensure_obs_installed():
                return
            if not self._authenticate():
                return
            for local_path, vault_name in self._sync_vaults:
                if vault_name in self._processes:
                    continue
                self._start_sync(local_path, vault_name)
        except Exception as e:
            log.error("Sync setup failed: %s", e)

    @property
    def is_active(self) -> bool:
        return bool(self._processes)

    def start_vault(self, vc: VaultConfig) -> None:
        """Start syncing a single vault. Called when a sync vault is added at runtime."""
        if not self._username:
            return
        local_path = vc.dir_path[5:] if vc.dir_path.startswith("sync:") else None
        if not local_path:
            return
        obs_vault_name = Path(local_path).name
        if obs_vault_name in self._processes:
            return  # already running
        self._start_sync(local_path, obs_vault_name)

    def stop(self) -> None:
        procs = list(self._processes.values())
        self._processes.clear()
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        deadline = time.time() + 2
        for proc in procs:
            remaining = max(0, deadline - time.time())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                proc.kill()

    def get_recent_log(self, n: int = 50) -> list[str]:
        with self._lock:
            entries = list(self._log)[-n:]
        return [
            f"{time.strftime('%H:%M:%S', time.localtime(ts))} [{name}] {line}"
            for ts, name, line in entries
        ]

    def get_latest_line(self) -> str | None:
        with self._lock:
            if not self._log:
                return None
            ts, name, line = self._log[-1]
        if time.time() - ts > 30:
            return None
        return line

    # -- internal --

    def _ensure_obs_installed(self) -> bool:
        if shutil.which("ob"):
            return True
        # npm global default prefix may not be user-writable; install to ~/.local instead
        user_prefix = os.path.expanduser("~/.local")
        cmd = ["npm", "install", "-g", "--prefix", user_prefix, "obsidian-headless"]
        self._log_cmd("system", cmd)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except Exception as e:
            log.error("Failed to install obsidian-headless: %s", e)
            return False
        if result.returncode != 0:
            log.error("npm install failed (rc=%d): %s", result.returncode, result.stderr.strip())
            return False
        # npm --prefix installs binaries to <prefix>/bin; ensure it's on PATH
        bin_dir = os.path.join(user_prefix, "bin")
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + bin_dir
        if not shutil.which("ob"):
            log.error("ob still not found after install (checked %s)", bin_dir)
            return False
        return True

    def _authenticate(self) -> bool:
        # Check if already authenticated — avoids rate-limit on rapid restarts
        try:
            check = subprocess.run(
                ["ob", "sync-list-remote"], capture_output=True, text=True, timeout=10,
            )
            if check.returncode == 0:
                log.info("ob already authenticated, skipping login")
                return True
        except Exception:
            pass  # fall through to login

        self._log_cmd("system", ["ob", "login", "--email", self._username, "--password", "***"])
        try:
            result = subprocess.run(
                ["ob", "login", "--email", self._username, "--password", self._password],
                capture_output=True, text=True, timeout=30,
            )
        except Exception as e:
            log.error("ob login failed: %s", e)
            return False
        if result.returncode != 0:
            log.error("ob login failed: %s", result.stderr.strip())
            return False
        return True

    def _start_sync(self, local_path: str, vault_name: str) -> None:
        os.makedirs(local_path, exist_ok=True)

        self._log_cmd(vault_name, ["ob", "sync-setup", "--vault", vault_name, "--path", local_path])
        try:
            result = subprocess.run(
                ["ob", "sync-setup", "--vault", vault_name, "--path", local_path],
                capture_output=True, text=True, timeout=30,
            )
        except Exception as e:
            log.error("ob sync-setup failed for %s: %s", vault_name, e)
            return
        if result.returncode != 0:
            log.error("ob sync-setup failed for %s: %s", vault_name, result.stderr.strip())
            return

        try:
            proc = subprocess.Popen(
                ["ob", "sync", "--continuous", "--path", local_path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
        except OSError as e:
            log.error("Failed to start ob sync for %s: %s", vault_name, e)
            return
        self._processes[vault_name] = proc
        t = threading.Thread(daemon=True, target=self._log_reader, args=(proc.stdout, vault_name))
        t.start()

    def _log_reader(self, stream, vault_name: str) -> None:
        for raw_line in stream:
            line = raw_line.decode(errors="replace").rstrip("\n\r")
            with self._lock:
                self._log.append((time.time(), vault_name, line))

    def _log_cmd(self, vault_name: str, cmd: list[str]) -> None:
        with self._lock:
            self._log.append((time.time(), vault_name, "$ " + " ".join(cmd)))
