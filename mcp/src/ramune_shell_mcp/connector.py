"""Connector to a remote worker daemon."""

from __future__ import annotations

import asyncio
import logging

from ramune_shell_protocol import Request, Response, ErrorCode
from ramune_shell_protocol.messages import ErrorInfo

log = logging.getLogger(__name__)


class WorkerConnector:
    """Sends requests to a worker daemon over TCP."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9800) -> None:
        self._host = host
        self._port = port

    async def call(self, method: str, params: dict | None = None, *, request_id: str) -> Response:
        """Send a request and return the response."""
        req = Request(
            id=request_id,
            method=method,
            params=params or {},
        )
        try:
            reader, writer = await asyncio.open_connection(self._host, self._port)
        except (OSError, ConnectionRefusedError) as e:
            log.error("connection failed to %s:%s: %s", self._host, self._port, e)
            return Response(
                id=req.id,
                error=ErrorInfo(code=ErrorCode.INTERNAL_ERROR, message=f"connection failed: {e}"),
            )
        try:
            writer.write(req.to_bytes())
            await writer.drain()
            resp = await Response.async_read(reader)
            return resp
        except (OSError, asyncio.IncompleteReadError) as e:
            log.error("communication error with %s:%s: %s", self._host, self._port, e)
            return Response(
                id=req.id,
                error=ErrorInfo(code=ErrorCode.INTERNAL_ERROR, message=f"communication error: {e}"),
            )
        finally:
            writer.close()
            await writer.wait_closed()
