"""End-to-end test: exec feature via worker."""

import asyncio

import pytest
import pytest_asyncio

from ramune_shell.worker.server import WorkerServer
from ramune_shell.mcp.connector import WorkerConnector
from ramune_shell.mcp.tasks import next_request_id as _rid

import ramune_shell.worker.handlers  # noqa: F401
from ramune_shell.worker.features.exec import register as register_exec

register_exec()


@pytest_asyncio.fixture
async def worker_port():
    srv = WorkerServer(host="127.0.0.1", port=0)
    srv._server = await asyncio.start_server(
        srv.handle_connection, "127.0.0.1", 0
    )
    port = srv._server.sockets[0].getsockname()[1]
    asyncio.create_task(srv._server.serve_forever())
    yield port
    srv._server.close()
    await srv._server.wait_closed()


@pytest.mark.asyncio
async def test_exec_echo(worker_port):
    connector = WorkerConnector(host="127.0.0.1", port=worker_port)
    resp = await connector.call("plugin:exec", {"command": "echo hello"}, request_id=_rid())
    assert resp.error is None
    assert resp.result["stdout"].strip() == "hello"
    assert resp.result["exit_code"] == 0


@pytest.mark.asyncio
async def test_exec_stderr(worker_port):
    connector = WorkerConnector(host="127.0.0.1", port=worker_port)
    resp = await connector.call("plugin:exec", {"command": "echo err >&2"}, request_id=_rid())
    assert resp.error is None
    assert resp.result["stderr"].strip() == "err"


@pytest.mark.asyncio
async def test_exec_exit_code(worker_port):
    connector = WorkerConnector(host="127.0.0.1", port=worker_port)
    resp = await connector.call("plugin:exec", {"command": "exit 42"}, request_id=_rid())
    assert resp.error is None
    assert resp.result["exit_code"] == 42


@pytest.mark.asyncio
async def test_exec_cwd(worker_port):
    connector = WorkerConnector(host="127.0.0.1", port=worker_port)
    resp = await connector.call("plugin:exec", {"command": "pwd", "cwd": "/tmp"}, request_id=_rid())
    assert resp.error is None
    assert resp.result["stdout"].strip() == "/tmp"
