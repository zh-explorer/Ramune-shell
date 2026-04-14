"""Physical connection layer: Connector / Listener protocols + TCP implementations.

Connector — client side, creates outbound connections.
Listener  — server side, accepts inbound connections.
Both return raw (reader, writer) pairs. Upper layers handle type bytes and framing.
"""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable


@runtime_checkable
class Connector(Protocol):
    """Client-side connection factory."""

    async def connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]: ...


@runtime_checkable
class Listener(Protocol):
    """Server-side connection acceptor."""

    async def bind(self) -> None: ...
    async def accept(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]: ...
    async def close(self) -> None: ...


class TcpConnector:
    """Connector over plain TCP."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port

    async def connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.open_connection(self._host, self._port)


class TcpListener:
    """Listener over plain TCP."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9800) -> None:
        self._host = host
        self._port = port
        self._server: asyncio.Server | None = None
        self._queue: asyncio.Queue[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = asyncio.Queue()

    async def bind(self) -> None:
        self._server = await asyncio.start_server(
            self._on_connect, self._host, self._port,
        )

    async def accept(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await self._queue.get()

    async def close(self) -> None:
        if self._server:
            self._server.close()
            self._server = None

    @property
    def port(self) -> int:
        """Actual bound port (useful when binding to port 0)."""
        if self._server and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return self._port

    async def _on_connect(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ) -> None:
        await self._queue.put((reader, writer))
