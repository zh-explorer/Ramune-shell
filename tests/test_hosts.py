"""Tests for host management."""

import asyncio

import pytest
import pytest_asyncio

from ramune_shell.worker.server import WorkerServer
from ramune_shell.mcp.hosts import HostManager

import ramune_shell.worker.handlers  # noqa: F401


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
async def test_add_remove_list():
    mgr = HostManager()
    assert mgr.list() == []

    mgr.add("test1", "10.0.0.1", 9800)
    mgr.add("test2", "10.0.0.2", 9801)
    hosts = mgr.list()
    assert len(hosts) == 2
    assert hosts[0]["name"] == "test1"
    assert hosts[1]["name"] == "test2"

    assert await mgr.remove("test1") is True
    assert await mgr.remove("nonexistent") is False
    assert len(mgr.list()) == 1


def test_get_connector():
    mgr = HostManager()
    mgr.add("test", "127.0.0.1", 9800)

    connector = mgr.get_connector("test")
    assert connector._host == "127.0.0.1"
    assert connector._port == 9800


def test_get_connector_unknown():
    mgr = HostManager()
    with pytest.raises(KeyError):
        mgr.get_connector("nonexistent")


@pytest.mark.asyncio
async def test_host_add_then_ping(worker_port):
    mgr = HostManager()
    mgr.add("local", "127.0.0.1", worker_port)

    connector = mgr.get_connector("local")
    from ramune_shell.mcp.tasks import next_request_id
    resp = await connector.call("ping", request_id=next_request_id())
    assert resp.error is None
    assert resp.result == {"pong": True}
