"""SSH integration tests. Require external infrastructure.

Run with: pytest tests/test_ssh_integration.py -m integration

Docker (Linux):
  docker run -d --name ramune-test -p 2222:22 -p 19800:9800 ramune-shell-test
  root / testpass

Windows:
  Set env vars: RAMUNE_WIN_HOST, RAMUNE_WIN_USER, RAMUNE_WIN_PASS
"""

import asyncio
import os
import tempfile

import pytest

from ramune_shell.mcp.ssh.session import SshSession, SshConfig
from ramune_shell.mcp.connector import WorkerConnector
from ramune_shell.mcp.session import open_session
from ramune_shell.mcp.tasks import next_request_id

pytestmark = pytest.mark.integration


# --- Docker Linux ---

DOCKER_SSH = SshConfig(host="127.0.0.1", port=2222, user="root", password="testpass")
DOCKER_WORKER_PORT = 9800
DOCKER_TCP_PORT = 19800


@pytest.mark.asyncio
async def test_docker_tcp():
    connector = WorkerConnector(host="127.0.0.1", port=DOCKER_TCP_PORT)
    resp = await connector.call("ping", request_id=next_request_id())
    assert resp.result == {"pong": True}
    resp = await connector.call("plugin:exec", {"command": "hostname"}, request_id=next_request_id())
    assert resp.error is None
    assert resp.result["exit_code"] == 0
    await connector.close_pool()


@pytest.mark.asyncio
async def test_docker_ssh_exec():
    session = SshSession(DOCKER_SSH, worker_port=DOCKER_WORKER_PORT)
    await session.start()
    result = await session.exec("whoami")
    assert result["stdout"].strip() == "root"
    await session.stop()


@pytest.mark.asyncio
async def test_docker_ssh_call():
    session = SshSession(DOCKER_SSH, worker_port=DOCKER_WORKER_PORT)
    await session.start()
    resp = await session.call("ping", request_id=next_request_id())
    assert resp.result == {"pong": True}
    resp = await session.call("plugin:exec", {"command": "uname -s"}, request_id=next_request_id())
    assert resp.result["stdout"].strip() == "Linux"
    await session.stop()


@pytest.mark.asyncio
async def test_docker_sftp():
    session = SshSession(DOCKER_SSH, worker_port=DOCKER_WORKER_PORT)
    await session.start()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("sftp test")
        local_path = f.name
    result = await session.sftp_put(local_path, "/tmp/sftp-test.txt")
    assert result["size"] == 9
    dl_path = local_path + ".dl"
    result = await session.sftp_get("/tmp/sftp-test.txt", dl_path)
    with open(dl_path) as f:
        assert f.read() == "sftp test"
    os.unlink(local_path)
    os.unlink(dl_path)
    await session.stop()


@pytest.mark.asyncio
async def test_docker_ssh_frame_channel():
    session = SshSession(DOCKER_SSH, worker_port=DOCKER_WORKER_PORT)
    await session.start()
    async with await open_session(session) as sess:
        assert sess.session_id.startswith("sess-")
    await session.stop()


# --- Windows (configure via env vars) ---

WIN_HOST = os.environ.get("RAMUNE_WIN_HOST", "")
WIN_USER = os.environ.get("RAMUNE_WIN_USER", "")
WIN_PASS = os.environ.get("RAMUNE_WIN_PASS", "")

_skip_win = pytest.mark.skipif(not WIN_HOST, reason="RAMUNE_WIN_HOST not set")


@_skip_win
@pytest.mark.asyncio
async def test_windows_ssh_exec():
    session = SshSession(SshConfig(host=WIN_HOST, user=WIN_USER, password=WIN_PASS))
    await session.start()
    result = await session.exec("hostname")
    assert result["exit_code"] == 0
    assert len(result["stdout"].strip()) > 0
    await session.stop()


@_skip_win
@pytest.mark.asyncio
async def test_windows_sftp():
    session = SshSession(SshConfig(host=WIN_HOST, user=WIN_USER, password=WIN_PASS))
    await session.start()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("win test")
        local_path = f.name
    remote_path = f"C:/Users/{WIN_USER}/ramune-test.txt"
    result = await session.sftp_put(local_path, remote_path)
    assert result["size"] == 8
    dl_path = local_path + ".dl"
    result = await session.sftp_get(remote_path, dl_path)
    with open(dl_path) as f:
        assert f.read() == "win test"
    await session.exec(f"del C:\\Users\\{WIN_USER}\\ramune-test.txt")
    os.unlink(local_path)
    os.unlink(dl_path)
    await session.stop()
