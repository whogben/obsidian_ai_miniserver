"""Tests for obsidian-headless sync manager."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from obs_ai_ms.sync import SyncManager


@pytest.fixture
def mock_subprocess():
    with patch("obs_ai_ms.sync.subprocess.Popen") as popen, patch("obs_ai_ms.sync.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stderr="", stdout="")
        proc_mock = MagicMock()
        proc_mock.stdout = BytesIO(b"")
        proc_mock.poll = MagicMock(return_value=None)
        popen.return_value = proc_mock
        yield run, popen


def test_start_sync_runs_sync_config_with_all_file_types(mock_subprocess, tmp_path):
    run_mock, popen_mock = mock_subprocess
    vault_path = str(tmp_path / "Test")
    sm = SyncManager("user@example.com", "secret", [])
    sm._start_sync(vault_path, "Test")

    assert run_mock.call_count == 2
    setup = run_mock.call_args_list[0][0][0]
    assert setup == ["ob", "sync-setup", "--vault", "Test", "--path", vault_path]
    cfg = run_mock.call_args_list[1][0][0]
    assert cfg == [
        "ob",
        "sync-config",
        "--path",
        vault_path,
        "--file-types",
        "image,audio,video,pdf,unsupported",
    ]
    popen_mock.assert_called_once()
    sync_args = popen_mock.call_args[0][0]
    assert sync_args == ["ob", "sync", "--continuous", "--path", vault_path]


def test_start_sync_stops_when_sync_setup_fails(mock_subprocess, tmp_path):
    run_mock, popen_mock = mock_subprocess
    run_mock.return_value = MagicMock(returncode=1, stderr="setup failed", stdout="")
    sm = SyncManager("u", "p", [])
    sm._start_sync(str(tmp_path / "V"), "V")
    assert run_mock.call_count == 1
    popen_mock.assert_not_called()


def test_start_sync_starts_continuous_even_when_sync_config_fails(mock_subprocess, tmp_path):
    run_mock, popen_mock = mock_subprocess
    run_mock.side_effect = [
        MagicMock(returncode=0, stderr="", stdout=""),
        MagicMock(returncode=1, stderr="no sync-config", stdout=""),
    ]
    sm = SyncManager("u", "p", [])
    sm._start_sync(str(tmp_path / "X"), "X")
    assert run_mock.call_count == 2
    popen_mock.assert_called_once()
