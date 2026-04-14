"""SSH integration tests. Require external infrastructure.

Run with: pytest tests/test_ssh_integration.py -m integration

Docker (Linux):
  docker run -d --name ramune-test -p 2222:22 -p 19800:9800 ramune-shell-test
  root / testpass
"""

import asyncio
import os
import tempfile

import pytest

from ramune_shell.transport import ClientTransport, ServerTransport, TcpConnector
from ramune_shell.transport.ssh import SshConnector, SshConfig
from ramune_shell.worker.dispatch import handle_session
from ramune_shell.worker.handlers import register_builtins
from ramune_shell.features.exec import register_worker as register_exec

pytestmark = pytest.mark.integration

DOCKER_SSH = SshConfig(host="127.0.0.1", port=2222, user="root", password="testpass")
DOCKER_WORKER_PORT = 9800
DOCKER_TCP_PORT = 19800

_registered = False

def _ensure_registered():
    global _registered
    if not _registered:
        register_builtins()
        register_exec()
        _registered = True


# --- TCP direct (dev mode) ---

async def test_docker_tcp_ping():
    _ensure_registered()
    ct = ClientTransport(TcpConnector("127.0.0.1", DOCKER_TCP_PORT))
    session = await ct.open_session()
    assert await session.ping() is True
    await session.close()
    await ct.close()


async def test_docker_tcp_exec():
    _ensure_registered()
    ct = ClientTransport(TcpConnector("127.0.0.1", DOCKER_TCP_PORT))
    session = await ct.open_session()
    resp = await session.request("exec", {"command": "hostname"})
    assert resp.error is None
    assert resp.result["exit_code"] == 0
    await session.close()
    await ct.close()


# --- SSH tunnel ---

async def test_docker_ssh_connector():
    """SshConnector implements Connector protocol."""
    connector = SshConnector(DOCKER_SSH, worker_port=DOCKER_WORKER_PORT)
    await connector.start()
    try:
        ct = ClientTransport(connector)
        session = await ct.open_session()
        assert await session.ping() is True
        await session.close()
        await ct.close()
    finally:
        await connector.stop()


async def test_docker_ssh_exec():
    connector = SshConnector(DOCKER_SSH, worker_port=DOCKER_WORKER_PORT)
    await connector.start()
    try:
        ct = ClientTransport(connector)
        session = await ct.open_session()
        resp = await session.request("exec", {"command": "uname -s"})
        assert resp.result["stdout"].strip() == "Linux"
        await session.close()
        await ct.close()
    finally:
        await connector.stop()


# --- SSH native capabilities ---

async def test_docker_ssh_native_exec():
    connector = SshConnector(DOCKER_SSH, worker_port=DOCKER_WORKER_PORT)
    await connector.start()
    try:
        result = await connector.exec("whoami")
        assert result["stdout"].strip() == "root"
    finally:
        await connector.stop()


async def test_docker_sftp():
    connector = SshConnector(DOCKER_SSH, worker_port=DOCKER_WORKER_PORT)
    await connector.start()
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("sftp test")
            local_path = f.name
        result = await connector.sftp_put(local_path, "/tmp/sftp-test.txt")
        assert result["size"] == 9
        dl_path = local_path + ".dl"
        result = await connector.sftp_get("/tmp/sftp-test.txt", dl_path)
        with open(dl_path) as f:
            assert f.read() == "sftp test"
        os.unlink(local_path)
        os.unlink(dl_path)
    finally:
        await connector.stop()


# --- Windows (configure via env vars) ---

WIN_HOST = os.environ.get("RAMUNE_WIN_HOST", "")
WIN_USER = os.environ.get("RAMUNE_WIN_USER", "")
WIN_PASS = os.environ.get("RAMUNE_WIN_PASS", "")

_skip_win = pytest.mark.skipif(not WIN_HOST, reason="RAMUNE_WIN_HOST not set")


@_skip_win
async def test_windows_ssh_exec():
    connector = SshConnector(
        SshConfig(host=WIN_HOST, user=WIN_USER, password=WIN_PASS),
    )
    await connector.start()
    try:
        result = await connector.exec("hostname")
        assert result["exit_code"] == 0
    finally:
        await connector.stop()


@_skip_win
async def test_windows_sftp():
    connector = SshConnector(
        SshConfig(host=WIN_HOST, user=WIN_USER, password=WIN_PASS),
    )
    await connector.start()
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("win test")
            local_path = f.name
        remote_path = f"C:/Users/{WIN_USER}/ramune-test.txt"
        result = await connector.sftp_put(local_path, remote_path)
        assert result["size"] == 8
        dl_path = local_path + ".dl"
        result = await connector.sftp_get(remote_path, dl_path)
        with open(dl_path) as f:
            assert f.read() == "win test"
        os.unlink(local_path)
        os.unlink(dl_path)
    finally:
        await connector.stop()
