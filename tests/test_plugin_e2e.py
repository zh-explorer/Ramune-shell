"""End-to-end test: plugin discovery + exec via worker."""

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from ramune_shell_worker.server import WorkerServer
from ramune_shell_worker.plugins import discover_plugins
from ramune_shell_worker.dispatch import register_plugins
from ramune_shell_mcp.connector import WorkerConnector
from ramune_shell_mcp.tasks import next_request_id as _rid

import ramune_shell_worker.handlers  # noqa: F401

PLUGINS_DIR = Path(__file__).resolve().parents[1] / "plugins"


@pytest_asyncio.fixture
async def worker_with_plugins():
    tools, handler_map = discover_plugins(PLUGINS_DIR)
    meta_map = {t["name"]: t for t in tools}
    register_plugins(handler_map, meta_map)

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
async def test_exec_echo(worker_with_plugins):
    connector = WorkerConnector(host="127.0.0.1", port=worker_with_plugins)
    resp = await connector.call("plugin:exec", {"command": "echo hello"}, request_id=_rid())
    assert resp.error is None
    assert resp.result["stdout"].strip() == "hello"
    assert resp.result["exit_code"] == 0


@pytest.mark.asyncio
async def test_exec_stderr(worker_with_plugins):
    connector = WorkerConnector(host="127.0.0.1", port=worker_with_plugins)
    resp = await connector.call("plugin:exec", {"command": "echo err >&2"}, request_id=_rid())
    assert resp.error is None
    assert resp.result["stderr"].strip() == "err"


@pytest.mark.asyncio
async def test_exec_exit_code(worker_with_plugins):
    connector = WorkerConnector(host="127.0.0.1", port=worker_with_plugins)
    resp = await connector.call("plugin:exec", {"command": "exit 42"}, request_id=_rid())
    assert resp.error is None
    assert resp.result["exit_code"] == 42


@pytest.mark.asyncio
async def test_exec_cwd(worker_with_plugins):
    connector = WorkerConnector(host="127.0.0.1", port=worker_with_plugins)
    resp = await connector.call("plugin:exec", {"command": "pwd", "cwd": "/tmp"}, request_id=_rid())
    assert resp.error is None
    assert resp.result["stdout"].strip() == "/tmp"


@pytest.mark.asyncio
async def test_list_plugins_shows_exec(worker_with_plugins):
    connector = WorkerConnector(host="127.0.0.1", port=worker_with_plugins)
    resp = await connector.call("list_plugins", request_id=_rid())
    assert resp.error is None
    names = [p["name"] for p in resp.result["plugins"]]
    assert "exec" in names
