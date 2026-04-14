"""Tests for FrameChannel: send/recv, send_msg/recv_msg, detach, lifecycle."""

import asyncio

import pytest

from ramune_shell.transport.channel import FrameChannel
from ramune_shell.transport.messages import Request, Response
from ramune_shell.transport.addr import OpId


async def _make_pair():
    """Create a connected pair of FrameChannels via TCP loopback."""
    ready = asyncio.Event()
    server_ch = None

    async def on_connect(reader, writer):
        nonlocal server_ch
        server_ch = FrameChannel(reader, writer)
        ready.set()

    server = await asyncio.start_server(on_connect, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    client_ch = FrameChannel(reader, writer)
    await ready.wait()
    return client_ch, server_ch, server


# --- raw bytes ---

async def test_send_recv():
    client, server, srv = await _make_pair()
    try:
        await client.send(b"hello")
        assert await server.recv() == b"hello"
        await server.send(b"world")
        assert await client.recv() == b"world"
    finally:
        await client.close()
        await server.close()
        srv.close()


async def test_multiple_frames():
    client, server, srv = await _make_pair()
    try:
        for i in range(10):
            await client.send(f"msg-{i}".encode())
        for i in range(10):
            assert await server.recv() == f"msg-{i}".encode()
    finally:
        await client.close()
        await server.close()
        srv.close()


async def test_large_frame():
    client, server, srv = await _make_pair()
    try:
        big = b"x" * 100_000
        await client.send(big)
        assert await server.recv() == big
    finally:
        await client.close()
        await server.close()
        srv.close()


async def test_recv_none_on_close():
    client, server, srv = await _make_pair()
    try:
        await client.close()
        await asyncio.sleep(0.05)
        assert await server.recv() is None
    finally:
        await server.close()
        srv.close()


async def test_recv_cancellable():
    client, server, srv = await _make_pair()
    try:
        task = asyncio.create_task(server.recv())
        await asyncio.sleep(0.05)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await client.close()
        await server.close()
        srv.close()


# --- typed messages ---

async def test_send_msg_recv_msg():
    client, server, srv = await _make_pair()
    try:
        req = Request(id=OpId(session="s1", seq="r1"), method="ping", params={})
        await client.send_msg(req)
        got = await server.recv_msg(Request)
        assert got is not None
        assert got.method == "ping"
        assert got.id.session == "s1"
    finally:
        await client.close()
        await server.close()
        srv.close()


# --- detach ---

async def test_detach_returns_raw_streams():
    client, server, srv = await _make_pair()
    try:
        reader, writer = client.detach()
        assert client.closed
        # Can still use raw streams
        writer.write(b"raw")
        await writer.drain()
        writer.close()
    finally:
        await server.close()
        srv.close()


async def test_detach_fails_with_buffered_data():
    client, server, srv = await _make_pair()
    try:
        await server.send(b"data")
        await asyncio.sleep(0.05)
        # Force data into client buffer without extracting a frame
        raw = await client._reader.read(1024)
        client._buf.extend(raw)
        with pytest.raises(RuntimeError, match="unprocessed data"):
            client.detach()
    finally:
        await client.close()
        await server.close()
        srv.close()


# --- context manager ---

async def test_context_manager():
    client, server, srv = await _make_pair()
    try:
        async with client as ch:
            await ch.send(b"test")
        assert client.closed
    finally:
        await server.close()
        srv.close()
