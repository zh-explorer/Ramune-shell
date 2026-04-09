"""Connector to a remote worker daemon.

Manages a connection pool for R/Q connections and provides methods
to open Frame/Raw channels for sessions.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque

from ramune_shell_protocol import (
    Request, Response, ErrorCode,
    TYPE_RQ, TYPE_FRAME,
    write_token,
)
from ramune_shell_protocol.messages import ErrorInfo
from ramune_shell_protocol.channel import _FRAME_HEADER

log = logging.getLogger(__name__)

# Connection pool settings
_POOL_MAX = 10
_POOL_KEEPALIVE = 60.0  # seconds


class WorkerConnector:
    """Sends requests to a worker daemon over TCP with connection pooling."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9800) -> None:
        self._host = host
        self._port = port
        self._pool: deque[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = deque()

    # --- R/Q ---

    async def call(self, method: str, params: dict | None = None, *, request_id: str) -> Response:
        """Send a request and return the response (R/Q channel)."""
        req = Request(id=request_id, method=method, params=params or {})
        reader, writer = await self._acquire_rq()
        if writer is None:
            return Response(
                id=req.id,
                error=ErrorInfo(code=ErrorCode.INTERNAL_ERROR, message="connection failed"),
            )
        try:
            writer.write(req.to_bytes())
            await writer.drain()
            resp = await Response.async_read(reader)
            self._release_rq(reader, writer)
            return resp
        except (OSError, asyncio.IncompleteReadError) as e:
            log.error("communication error with %s:%s: %s", self._host, self._port, e)
            self._close_conn(writer)
            return Response(
                id=req.id,
                error=ErrorInfo(code=ErrorCode.INTERNAL_ERROR, message=f"communication error: {e}"),
            )

    async def _acquire_rq(self) -> tuple[asyncio.StreamReader | None, asyncio.StreamWriter | None]:
        """Get an R/Q connection from pool or create new."""
        while self._pool:
            reader, writer = self._pool.popleft()
            if not writer.is_closing():
                return reader, writer
        try:
            reader, writer = await asyncio.open_connection(self._host, self._port)
            writer.write(TYPE_RQ)
            await writer.drain()
            return reader, writer
        except (OSError, ConnectionRefusedError) as e:
            log.error("connection failed to %s:%s: %s", self._host, self._port, e)
            return None, None

    def _release_rq(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Return an R/Q connection to pool."""
        if len(self._pool) < _POOL_MAX and not writer.is_closing():
            self._pool.append((reader, writer))
        else:
            self._close_conn(writer)

    # --- Frame channel ---

    async def open_frame_channel(self, token: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | None:
        """Open a Frame channel and send the token handshake."""
        try:
            reader, writer = await asyncio.open_connection(self._host, self._port)
            writer.write(TYPE_FRAME)
            await writer.drain()
            await write_token(writer, token)
            return reader, writer
        except (OSError, ConnectionRefusedError) as e:
            log.error("frame channel failed to %s:%s: %s", self._host, self._port, e)
            return None

    # --- cleanup ---

    @staticmethod
    def _close_conn(writer: asyncio.StreamWriter) -> None:
        if not writer.is_closing():
            writer.close()

    async def close_pool(self) -> None:
        """Close all pooled connections."""
        while self._pool:
            _, writer = self._pool.popleft()
            self._close_conn(writer)
