"""Tests for the worker TCP server."""

import asyncio

import pytest
import pytest_asyncio

from ramune_shell.protocol import Request, Response
from ramune_shell.worker.server import WorkerServer

# Import handlers to register them via @handler decorator
import ramune_shell.worker.handlers  # noqa: F401


async def send_request(port: int, req: Request) -> Response:
    """Connect, send type byte + request, read the response."""
    from ramune_shell.protocol import TYPE_RQ
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(TYPE_RQ)
    writer.write(req.to_bytes())
    await writer.drain()
    resp = await Response.async_read(reader)
    writer.close()
    await writer.wait_closed()
    return resp


@pytest_asyncio.fixture
async def server_port():
    """Start a WorkerServer on a random port and yield the port number."""
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
async def test_ping(server_port):
    req = Request(id="t-001", method="ping")
    resp = await send_request(server_port, req)
    assert resp.id == "t-001"
    assert resp.result == {"pong": True}
    assert resp.error is None


@pytest.mark.asyncio
async def test_list_plugins(server_port):
    req = Request(id="t-002", method="list_plugins")
    resp = await send_request(server_port, req)
    assert resp.id == "t-002"
    assert "plugins" in resp.result
    assert isinstance(resp.result["plugins"], list)


@pytest.mark.asyncio
async def test_unknown_method(server_port):
    req = Request(id="t-003", method="nonexistent")
    resp = await send_request(server_port, req)
    assert resp.id == "t-003"
    assert resp.error is not None
    assert resp.error.code == -3  # METHOD_NOT_FOUND


@pytest.mark.asyncio
async def test_unknown_plugin(server_port):
    req = Request(id="t-004", method="plugin:nonexistent")
    resp = await send_request(server_port, req)
    assert resp.id == "t-004"
    assert resp.error is not None
    assert resp.error.code == -3  # METHOD_NOT_FOUND


@pytest.mark.asyncio
async def test_concurrent_requests(server_port):
    """Multiple connections in parallel should all get responses."""
    reqs = [Request(id=f"t-{i}", method="ping") for i in range(10)]
    tasks = [send_request(server_port, r) for r in reqs]
    responses = await asyncio.gather(*tasks)
    for i, resp in enumerate(responses):
        assert resp.id == f"t-{i}"
        assert resp.result == {"pong": True}
