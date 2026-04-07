"""TCP server for the worker daemon.

Listens on a local port, accepts one connection per request.
Each connection carries exactly one Request-Response exchange.
"""

from __future__ import annotations

import asyncio
import logging

from ramune_shell_protocol import Request
from ramune_shell_worker.dispatch import dispatch

log = logging.getLogger(__name__)


class WorkerServer:
    """Async TCP server that dispatches incoming requests."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9800) -> None:
        self._host = host
        self._port = port
        self._server: asyncio.Server | None = None

    async def handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single connection: read one Request, dispatch, send Response."""
        peer = writer.get_extra_info("peername")
        try:
            req = await Request.async_read(reader)
            log.debug("request %s: %s from %s", req.id, req.method, peer)
            response = await dispatch(req)
            writer.write(response.to_bytes())
            await writer.drain()
        except Exception:
            log.exception("error handling connection from %s", peer)
        finally:
            writer.close()
            await writer.wait_closed()

    async def serve(self) -> None:
        """Start serving and block until cancelled."""
        self._server = await asyncio.start_server(
            self.handle_connection,
            self._host,
            self._port,
        )
        addr = self._server.sockets[0].getsockname()
        log.info("worker listening on %s:%s", addr[0], addr[1])
        async with self._server:
            await self._server.serve_forever()
