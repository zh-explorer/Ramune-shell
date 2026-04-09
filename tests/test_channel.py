"""Tests for FrameChannel and connection protocol."""

import asyncio

import pytest
import pytest_asyncio

from ramune_shell.protocol.channel import (
    FrameChannel, TYPE_RQ, TYPE_FRAME,
    write_frame, read_frame, write_token, read_token,
)


async def _make_pair() -> tuple[FrameChannel, FrameChannel]:
    """Create a connected pair of FrameChannels via TCP loopback."""
    ready = asyncio.Event()
    server_channel = None

    async def on_connect(reader, writer):
        nonlocal server_channel
        server_channel = FrameChannel(reader, writer)
        ready.set()

    server = await asyncio.start_server(on_connect, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    client_channel = FrameChannel(reader, writer)
    await ready.wait()
    return client_channel, server_channel, server


@pytest.mark.asyncio
async def test_frame_channel_send_recv():
    client, server, srv = await _make_pair()
    try:
        await client.send(b"hello")
        data = await server.recv()
        assert data == b"hello"

        await server.send(b"world")
        data = await client.recv()
        assert data == b"world"
    finally:
        await client.close()
        await server.close()
        srv.close()


@pytest.mark.asyncio
async def test_frame_channel_multiple_frames():
    client, server, srv = await _make_pair()
    try:
        for i in range(10):
            await client.send(f"msg-{i}".encode())
        for i in range(10):
            data = await server.recv()
            assert data == f"msg-{i}".encode()
    finally:
        await client.close()
        await server.close()
        srv.close()


@pytest.mark.asyncio
async def test_frame_channel_large_frame():
    client, server, srv = await _make_pair()
    try:
        big = b"x" * 100_000
        await client.send(big)
        data = await server.recv()
        assert data == big
    finally:
        await client.close()
        await server.close()
        srv.close()


@pytest.mark.asyncio
async def test_frame_channel_recv_returns_none_on_close():
    client, server, srv = await _make_pair()
    try:
        await client.close()
        # Give event loop a tick to propagate close
        await asyncio.sleep(0.05)
        data = await server.recv()
        assert data is None
    finally:
        await server.close()
        srv.close()


@pytest.mark.asyncio
async def test_frame_channel_recv_cancellable():
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


@pytest.mark.asyncio
async def test_frame_channel_bidirectional_concurrent():
    """Both sides send and recv simultaneously."""
    client, server, srv = await _make_pair()
    try:
        async def client_work():
            for i in range(5):
                await client.send(f"c{i}".encode())
            results = []
            for _ in range(5):
                results.append(await client.recv())
            return results

        async def server_work():
            results = []
            for _ in range(5):
                results.append(await server.recv())
            for i in range(5):
                await server.send(f"s{i}".encode())
            return results

        client_results, server_results = await asyncio.gather(
            client_work(), server_work()
        )
        assert server_results == [f"c{i}".encode() for i in range(5)]
        assert client_results == [f"s{i}".encode() for i in range(5)]
    finally:
        await client.close()
        await server.close()
        srv.close()


@pytest.mark.asyncio
async def test_frame_channel_context_manager():
    client, server, srv = await _make_pair()
    try:
        async with client as ch:
            await ch.send(b"test")
        assert client.closed
    finally:
        await server.close()
        srv.close()
