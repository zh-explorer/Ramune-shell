"""TCP server for the worker daemon.

Handles two connection types based on the first byte:
  0x01 (R/Q)   — request-response loop, connection pooled
  0x02 (Frame) — framed session channel, matched by token
"""

from __future__ import annotations

import asyncio
import logging

from ramune_shell_protocol import Request, TYPE_RQ, TYPE_FRAME, read_token
from ramune_shell_worker.dispatch import dispatch
from ramune_shell_worker.sessions import session_manager

log = logging.getLogger(__name__)


class WorkerServer:
    """Async TCP server with typed connections."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9800) -> None:
        self._host = host
        self._port = port
        self._server: asyncio.Server | None = None

    async def handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Read type byte and route to appropriate handler."""
        peer = writer.get_extra_info("peername")
        try:
            type_byte = await reader.readexactly(1)

            if type_byte == TYPE_RQ:
                try:
                    await self._handle_rq(reader, writer, peer)
                except asyncio.IncompleteReadError:
                    pass  # client closed connection, normal for pooled R/Q
                finally:
                    writer.close()
                    await writer.wait_closed()

            elif type_byte == TYPE_FRAME:
                # Session owns the connection — don't close here
                await self._handle_frame(reader, writer, peer)

            else:
                log.warning("unknown connection type 0x%02x from %s", type_byte[0], peer)
                writer.close()
                await writer.wait_closed()

        except asyncio.IncompleteReadError:
            log.debug("connection closed before type byte from %s", peer)
            writer.close()
            await writer.wait_closed()
        except Exception:
            log.exception("error handling connection from %s", peer)
            writer.close()
            await writer.wait_closed()

    async def _handle_rq(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        peer,
    ) -> None:
        """Handle R/Q connection: loop request-response until closed."""
        while True:
            req = await Request.async_read(reader)
            log.debug("R/Q %s: %s from %s", req.id, req.method, peer)
            response = await dispatch(req)
            writer.write(response.to_bytes())
            await writer.drain()

    async def _handle_frame(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        peer,
    ) -> None:
        """Handle Frame channel: read token, attach to session."""
        token = await read_token(reader)
        log.debug("Frame channel token=%s from %s", token, peer)
        session_manager.attach(token, reader, writer)

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
