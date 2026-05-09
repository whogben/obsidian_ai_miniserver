"""CLI smoke tests: verify obs_ai_ms entry point starts without crashing."""

import os
import subprocess
import sys
import time

from typer.testing import CliRunner

from obs_ai_ms.entry import app

runner = CliRunner()


def test_cli_no_args_shows_error():
    """CLI with no args should show usage/error, not crash with asyncio ValueError."""
    result = runner.invoke(app, [])
    assert result.exit_code != 0
    assert "ValueError" not in result.output


def _start_server(args, env=None):
    """Start server subprocess, return proc. Caller must terminate."""
    cmd = [sys.executable, "-m", "obs_ai_ms.entry"] + args
    return subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )


def _assert_alive(proc):
    poll = proc.poll()
    assert poll is None, f"Server crashed:\n{proc.stderr.read().decode()}"


def test_cli_server_starts_with_vault(tmp_path):
    """Server starts with a single --vault option."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / ".obsidian").mkdir()

    proc = _start_server([
        "start", "--vault", f"testvault:{vault}",
        "--admin-token", "test123", "--port", "0",
    ])
    try:
        time.sleep(3)
        _assert_alive(proc)
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_cli_server_starts_no_vaults(tmp_path):
    """Server starts fine with no vaults — can be added later."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    proc = _start_server([
        "start", "--config", str(config_dir / "test_config.json"),
        "--admin-token", "test123", "--port", "0",
    ])
    try:
        time.sleep(3)
        _assert_alive(proc)
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_cli_env_var_admin_token(tmp_path):
    """OBS_AI_MS_ADMIN_TOKEN env var supplies admin token without --admin-token flag."""
    vault = tmp_path / "vault"
    vault.mkdir()
    env = {**os.environ, "OBS_AI_MS_ADMIN_TOKEN": "test123"}

    proc = _start_server(
        ["start", "--vault", f"testvault:{vault}", "--port", "0"],
        env=env,
    )
    try:
        time.sleep(3)
        _assert_alive(proc)
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_cli_env_var_port(tmp_path):
    """OBS_AI_MS_PORT env var supplies port without --port flag."""
    vault = tmp_path / "vault"
    vault.mkdir()
    env = {**os.environ, "OBS_AI_MS_PORT": "0"}

    proc = _start_server(
        ["start", "--vault", f"testvault:{vault}", "--admin-token", "test123"],
        env=env,
    )
    try:
        time.sleep(3)
        _assert_alive(proc)
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_cli_env_var_host(tmp_path):
    """OBS_AI_MS_HOST env var supplies host without --host flag."""
    vault = tmp_path / "vault"
    vault.mkdir()
    env = {**os.environ, "OBS_AI_MS_HOST": "127.0.0.1"}

    proc = _start_server(
        ["start", "--vault", f"testvault:{vault}", "--admin-token", "test123", "--port", "0"],
        env=env,
    )
    try:
        time.sleep(3)
        _assert_alive(proc)
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_cli_multiple_vaults(tmp_path):
    """Server starts with multiple --vault options."""
    vault1 = tmp_path / "work"
    vault1.mkdir()
    (vault1 / ".obsidian").mkdir()

    vault2 = tmp_path / "personal"
    vault2.mkdir()
    (vault2 / ".obsidian").mkdir()

    proc = _start_server([
        "start",
        "--vault", f"work:{vault1}",
        "--vault", f"personal:{vault2}",
        "--admin-token", "test123", "--port", "0",
    ])
    try:
        time.sleep(3)
        _assert_alive(proc)
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_cli_config_option(tmp_path):
    """--config flag sets config file path and config is created on start."""
    config_path = tmp_path / "myconfig.json"

    proc = _start_server([
        "start", "--config", str(config_path),
        "--admin-token", "test123", "--port", "0",
    ])
    try:
        time.sleep(3)
        _assert_alive(proc)
        assert config_path.exists(), "Config file was not created"
    finally:
        proc.terminate()
        proc.wait(timeout=5)
