"""Connector to a remote worker daemon."""

from __future__ import annotations

import asyncio
import itertools

from ramune_shell_protocol import Request, Response


class WorkerConnector:
    """Sends requests to a worker daemon over TCP."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9800) -> None:
        self._host = host
        self._port = port
        self._id_counter = itertools.count(1)

    def _next_id(self) -> str:
        return f"r-{next(self._id_counter):06d}"

    async def call(self, method: str, params: dict | None = None) -> Response:
        """Send a request and return the response.

        Opens a new TCP connection per request (each request is an
        independent channel, per protocol rules).
        """
        req = Request(
            id=self._next_id(),
            method=method,
            params=params or {},
        )
        reader, writer = await asyncio.open_connection(self._host, self._port)
        try:
            writer.write(req.to_bytes())
            await writer.drain()
            resp = await Response.async_read(reader)
            return resp
        finally:
            writer.close()
            await writer.wait_closed()
