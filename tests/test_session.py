"""Tests for session creation and lifecycle (MCP + Worker sides)."""

import asyncio

import pytest

from ramune_shell.worker.server import WorkerServer
from ramune_shell.worker.sessions import session_manager
from ramune_shell.mcp.connector import WorkerConnector
from ramune_shell.mcp.session import open_session
from ramune_shell.mcp.tasks import next_request_id

import ramune_shell.worker.handlers  # noqa: F401


async def _run_with_server(coro_fn):
    """Run a test function with a fresh worker server."""
    session_manager._sessions.clear()
    session_manager._tokens.clear()

    srv = WorkerServer(host="127.0.0.1", port=0)
    srv._server = await asyncio.start_server(
        srv.handle_connection, "127.0.0.1", 0
    )
    port = srv._server.sockets[0].getsockname()[1]
    serve_task = asyncio.create_task(srv._server.serve_forever())
    try:
        await coro_fn(port)
    finally:
        srv._server.close()
        serve_task.cancel()
        # Cancel all tasks except ourselves
        current = asyncio.current_task()
        for t in list(asyncio.all_tasks()):
            if t is not current and not t.done():
                t.cancel()
        await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_open_session_creates_channel():
    async def _test(port):
        connector = WorkerConnector(host="127.0.0.1", port=port)
        async with await open_session(connector) as session:
            assert session.session_id.startswith("sess-")
            assert not session.channel.closed
        await connector.close_pool()
    await _run_with_server(_test)


@pytest.mark.asyncio
async def test_session_send_recv():
    async def _test(port):
        connector = WorkerConnector(host="127.0.0.1", port=port)
        async with await open_session(connector) as session:
            sid = session.session_id
            await asyncio.sleep(0.1)
            worker_session = session_manager.take(sid)
            assert worker_session is not None
            await worker_session.ready.wait()

            await session.send(b"hello from mcp")
            data = await worker_session.channel.recv()
            assert data == b"hello from mcp"

            await worker_session.channel.send(b"hello from worker")
            data = await session.recv()
            assert data == b"hello from worker"

            await worker_session.channel.close()
        await connector.close_pool()
    await _run_with_server(_test)


@pytest.mark.asyncio
async def test_session_close_cleanup():
    async def _test(port):
        connector = WorkerConnector(host="127.0.0.1", port=port)
        session = await open_session(connector)
        sid = session.session_id
        await asyncio.sleep(0.1)
        worker_session = session_manager.take(sid)
        assert worker_session is not None
        await worker_session.ready.wait()

        await session.close()
        await asyncio.sleep(0.05)
        data = await worker_session.channel.recv()
        assert data is None
        await worker_session.channel.close()
        await connector.close_pool()
    await _run_with_server(_test)


@pytest.mark.asyncio
async def test_session_context_manager():
    async def _test(port):
        connector = WorkerConnector(host="127.0.0.1", port=port)
        async with await open_session(connector) as session:
            assert not session.channel.closed
        assert session.channel.closed
        await connector.close_pool()
    await _run_with_server(_test)


@pytest.mark.asyncio
async def test_connection_pool_reuse():
    async def _test(port):
        connector = WorkerConnector(host="127.0.0.1", port=port)
        resp = await connector.call("ping", request_id=next_request_id())
        assert resp.result == {"pong": True}
        assert len(connector._pool) == 1
        resp = await connector.call("ping", request_id=next_request_id())
        assert resp.result == {"pong": True}
        assert len(connector._pool) == 1
        await connector.close_pool()
    await _run_with_server(_test)


@pytest.mark.asyncio
async def test_connection_pool_concurrent():
    async def _test(port):
        connector = WorkerConnector(host="127.0.0.1", port=port)
        tasks = [connector.call("ping", request_id=next_request_id()) for _ in range(5)]
        responses = await asyncio.gather(*tasks)
        for resp in responses:
            assert resp.result == {"pong": True}
        assert len(connector._pool) == 5
        await connector.close_pool()
    await _run_with_server(_test)
