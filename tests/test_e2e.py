"""End-to-end test: MCP connector -> Worker daemon."""

import asyncio

import pytest
import pytest_asyncio

from ramune_shell_worker.server import WorkerServer
from ramune_shell_mcp.connector import WorkerConnector

import ramune_shell_worker.handlers  # noqa: F401


@pytest_asyncio.fixture
async def worker_port():
    """Start a worker on a random port."""
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
async def test_e2e_ping(worker_port):
    connector = WorkerConnector(host="127.0.0.1", port=worker_port)
    resp = await connector.call("ping")
    assert resp.error is None
    assert resp.result == {"pong": True}


@pytest.mark.asyncio
async def test_e2e_list_plugins(worker_port):
    connector = WorkerConnector(host="127.0.0.1", port=worker_port)
    resp = await connector.call("list_plugins")
    assert resp.error is None
    assert resp.result == {"plugins": []}


@pytest.mark.asyncio
async def test_e2e_unknown_method(worker_port):
    connector = WorkerConnector(host="127.0.0.1", port=worker_port)
    resp = await connector.call("nonexistent")
    assert resp.error is not None


@pytest.mark.asyncio
async def test_e2e_concurrent(worker_port):
    connector = WorkerConnector(host="127.0.0.1", port=worker_port)
    tasks = [connector.call("ping") for _ in range(10)]
    responses = await asyncio.gather(*tasks)
    for resp in responses:
        assert resp.error is None
        assert resp.result == {"pong": True}
