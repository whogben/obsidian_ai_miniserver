"""CLI smoke tests: verify obs_ai_ms entry point starts without crashing."""

import os
import subprocess
import sys
import time

import pytest
from typer.testing import CliRunner

from obs_ai_ms.entry import app

runner = CliRunner()


def test_cli_no_args_shows_error():
    """CLI with no args should show usage/error, not crash with asyncio ValueError."""
    result = runner.invoke(app, [])
    assert result.exit_code != 0
    assert "ValueError" not in result.output


def test_cli_server_starts_and_stays_alive(tmp_path):
    """End-to-end: CLI starts server process without crashing."""
    vault = tmp_path / "vault"
    vault.mkdir()

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "obs_ai_ms.entry", "start", str(vault),
            "--admin-token", "test123", "--port", "0",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        time.sleep(3)
        poll = proc.poll()
        assert poll is None, f"Server crashed:\n{proc.stderr.read().decode()}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_cli_env_var_admin_token(tmp_path):
    """OBS_AI_MS_ADMIN_TOKEN env var supplies admin token without --admin-token flag."""
    vault = tmp_path / "vault"
    vault.mkdir()
    env = {**os.environ, "OBS_AI_MS_ADMIN_TOKEN": "test123"}

    proc = subprocess.Popen(
        [sys.executable, "-m", "obs_ai_ms.entry", "start", str(vault),
         "--port", "0"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )
    try:
        time.sleep(3)
        assert proc.poll() is None, f"Server crashed:\n{proc.stderr.read().decode()}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_cli_env_var_port(tmp_path):
    """OBS_AI_MS_PORT env var supplies port without --port flag."""
    vault = tmp_path / "vault"
    vault.mkdir()
    env = {**os.environ, "OBS_AI_MS_PORT": "0"}

    proc = subprocess.Popen(
        [sys.executable, "-m", "obs_ai_ms.entry", "start", str(vault),
         "--admin-token", "test123"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )
    try:
        time.sleep(3)
        assert proc.poll() is None, f"Server crashed:\n{proc.stderr.read().decode()}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_cli_env_var_host(tmp_path):
    """OBS_AI_MS_HOST env var supplies host without --host flag."""
    vault = tmp_path / "vault"
    vault.mkdir()
    env = {**os.environ, "OBS_AI_MS_HOST": "127.0.0.1"}

    proc = subprocess.Popen(
        [sys.executable, "-m", "obs_ai_ms.entry", "start", str(vault),
         "--admin-token", "test123", "--port", "0"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )
    try:
        time.sleep(3)
        assert proc.poll() is None, f"Server crashed:\n{proc.stderr.read().decode()}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)
