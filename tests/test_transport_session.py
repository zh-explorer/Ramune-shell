"""Tests for ClientTransport/ServerTransport + ClientSession/ServerSession."""

import asyncio

import pytest

from ramune_shell.transport import (
    ClientTransport, ServerTransport, TcpConnector, TcpListener,
    Request, Response,
)


async def _make_transport_pair():
    """Create connected ClientTransport + ServerTransport on loopback."""
    listener = TcpListener("127.0.0.1", 0)
    server_transport = ServerTransport(listener)
    await server_transport.start()
    port = server_transport.port
    client_transport = ClientTransport(TcpConnector("127.0.0.1", port))
    return client_transport, server_transport


# --- basic R/Q ---

async def test_ping():
    ct, st = await _make_transport_pair()
    try:
        session = await ct.open_session()
        assert await session.ping() is True
        await session.close()
    finally:
        await st.close()
        await ct.close()


async def test_request_response():
    """Client sends request, server dispatch returns result."""
    ct, st = await _make_transport_pair()

    async def _server():
        session = await st.accept_session()
        req = await session.get_request()
        assert req is not None
        assert req.method == "echo"
        await session.send_response(req, {"echoed": req.params["msg"]})

    server_task = asyncio.create_task(_server())
    try:
        session = await ct.open_session()
        resp = await session.request("echo", {"msg": "hello"})
        assert resp.error is None
        assert resp.result == {"echoed": "hello"}
        await session.close()
        await server_task
    finally:
        await st.close()
        await ct.close()


async def test_multiple_requests_same_session():
    """Multiple R/Q on the same session reuse pooled connections."""
    ct, st = await _make_transport_pair()

    async def _server():
        session = await st.accept_session()
        for _ in range(3):
            req = await session.get_request()
            if req is None:
                break
            await session.send_response(req, {"n": req.params["n"]})

    server_task = asyncio.create_task(_server())
    try:
        session = await ct.open_session()
        for i in range(3):
            resp = await session.request("count", {"n": i})
            assert resp.result == {"n": i}
        await session.close()
        await server_task
    finally:
        await st.close()
        await ct.close()


# --- close_session ---

async def test_close_session():
    """Client close sends close_session, server session ends."""
    ct, st = await _make_transport_pair()

    async def _server():
        session = await st.accept_session()
        req = await session.get_request()
        assert req is not None
        await session.send_response(req, {"ok": True})
        # After close_session, get_request returns None
        req2 = await session.get_request()
        assert req2 is None

    server_task = asyncio.create_task(_server())
    try:
        session = await ct.open_session()
        resp = await session.request("test", {})
        assert resp.result == {"ok": True}
        await session.close()
        await asyncio.wait_for(server_task, timeout=5.0)
    finally:
        await st.close()
        await ct.close()


# --- connection pool reuse ---

async def test_pool_reuse():
    ct, st = await _make_transport_pair()
    try:
        s1 = await ct.open_session()
        assert await s1.ping()
        pool_size_after_first = len(ct._pool)
        assert await s1.ping()
        # Connection returned to pool and reused
        assert len(ct._pool) >= pool_size_after_first
        await s1.close()
    finally:
        await st.close()
        await ct.close()


# --- concurrent sessions ---

async def test_concurrent_sessions():
    """Multiple sessions in parallel."""
    ct, st = await _make_transport_pair()

    async def _server_loop():
        for _ in range(3):
            session = await st.accept_session()
            asyncio.create_task(_handle(session))

    async def _handle(session):
        req = await session.get_request()
        if req:
            await session.send_response(req, {"session": req.params["id"]})

    asyncio.create_task(_server_loop())
    try:
        async def _client(i):
            session = await ct.open_session()
            resp = await session.request("test", {"id": i})
            assert resp.result == {"session": i}
            await session.close()

        await asyncio.gather(_client(1), _client(2), _client(3))
    finally:
        await st.close()
        await ct.close()
