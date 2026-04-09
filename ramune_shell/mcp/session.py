"""MCP-side session for full-duplex Frame communication with worker."""

from __future__ import annotations

from ramune_shell.protocol.channel import FrameChannel
from ramune_shell.mcp.tasks import next_request_id


class Session:
    """Full-duplex Frame channel to a worker. Use as async context manager."""

    def __init__(self, session_id: str, channel: FrameChannel) -> None:
        self.session_id = session_id
        self.channel = channel

    async def send(self, data: bytes) -> None:
        await self.channel.send(data)

    async def recv(self) -> bytes | None:
        return await self.channel.recv()

    async def close(self) -> None:
        await self.channel.close()

    async def __aenter__(self) -> Session:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()


async def open_session(connector) -> Session:
    """Open a session: R/Q to get token, then Frame channel."""
    resp = await connector.call("open_session", request_id=next_request_id())
    if resp.error:
        raise ConnectionError(f"open_session failed: {resp.error.message}")

    session_id = resp.result["session_id"]
    token = resp.result["token"]

    result = await connector.open_frame_channel(token)
    if result is None:
        raise ConnectionError("failed to open Frame channel")

    reader, writer = result
    channel = FrameChannel(reader, writer)
    return Session(session_id, channel)
