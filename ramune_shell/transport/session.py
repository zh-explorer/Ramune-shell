"""Session layer: the highest transport abstraction.

ClientTransport + ClientSession — MCP side (send requests).
ServerTransport + ServerSession — Worker side (receive requests).

All connections use FrameChannel as the underlying transport unit.
R/Q connections are pooled; streaming channels are taken permanently.

Internal protocol commands (ping, close_session, open_frame_channel)
are handled inside this layer, not exposed to upper layers.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from collections import deque
from typing import Any

from ramune_shell.transport.addr import OpId, new_session
from ramune_shell.transport.channel import (
    TYPE_RQ, TYPE_FRAME,
    FrameChannel,
    write_id, read_id,
)
from ramune_shell.transport.connection import Connector, Listener
from ramune_shell.transport.messages import (
    Request, Response, ErrorCode, ErrorInfo,
)

log = logging.getLogger(__name__)

_PING = "ping"
_CLOSE_SESSION = "close_session"
_OPEN_FRAME_CHANNEL = "open_frame_channel"

_POOL_MAX = 10
_SESSION_TTL = 300.0


# ============================================================
# Client side
# ============================================================

class ClientTransport:
    """MCP-side transport: FrameChannel pool + session factory."""

    def __init__(self, connector: Connector, pool_max: int = _POOL_MAX) -> None:
        self._connector = connector
        self._pool_max = pool_max
        self._pool: deque[FrameChannel] = deque()

    async def open_session(self) -> "ClientSession":
        return ClientSession(self, new_session())

    async def close(self) -> None:
        while self._pool:
            ch = self._pool.popleft()
            await ch.close()

    async def _acquire_rq(self) -> FrameChannel:
        """Get an R/Q FrameChannel from pool or create new."""
        while self._pool:
            ch = self._pool.popleft()
            if ch.closed:
                continue
            return ch
        reader, writer = await self._connector.connect()
        writer.write(TYPE_RQ)
        await writer.drain()
        return FrameChannel(reader, writer)

    def _release_rq(self, ch: FrameChannel) -> None:
        if len(self._pool) < self._pool_max and not ch.closed:
            self._pool.append(ch)
        else:
            asyncio.ensure_future(ch.close())

    async def _open_frame_stream(self, oid: OpId) -> FrameChannel:
        """Open a new Frame connection with handshake."""
        reader, writer = await self._connector.connect()
        writer.write(TYPE_FRAME)
        await writer.drain()
        await write_id(writer, oid)
        return FrameChannel(reader, writer)


class ClientSession:
    """One feature invocation's transport session on the MCP side."""

    def __init__(self, transport: ClientTransport, sid) -> None:
        self._transport = transport
        self._sid = sid
        self._op_counter = itertools.count(1)
        self._frame_channels: dict[str, FrameChannel] = {}
        self._closed = False

    def get_session_id(self) -> str:
        return str(self._sid)

    def _next_op(self) -> OpId:
        return OpId(session=str(self._sid), seq=f"req-{next(self._op_counter):04d}")

    async def request(self, method: str, params: dict | None = None) -> Response:
        oid = self._next_op()
        req = Request(id=oid, method=method, params=params or {})
        ch = await self._transport._acquire_rq()
        try:
            await ch.send_msg(req)
            resp = await ch.recv_msg(Response)
            if resp is None:
                raise ConnectionError("connection closed")
            self._transport._release_rq(ch)
            return resp
        except asyncio.CancelledError:
            await ch.close()
            raise
        except Exception as e:
            await ch.close()
            return Response(
                id=oid,
                error=ErrorInfo(code=int(ErrorCode.INTERNAL_ERROR), message=str(e)),
            )

    async def open_frame_channel(self) -> FrameChannel:
        oid = self._next_op()
        resp = await self.request(_OPEN_FRAME_CHANNEL, {})
        if resp.error is not None:
            raise RuntimeError(f"open_frame_channel failed: {resp.error.message}")
        return await self._transport._open_frame_stream(oid)

    async def ping(self) -> bool:
        resp = await self.request(_PING, {})
        return resp.error is None and resp.result.get("pong") is True

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for ch in list(self._frame_channels.values()):
            try:
                await ch.close()
            except Exception:
                pass
        self._frame_channels.clear()
        try:
            await self.request(_CLOSE_SESSION, {"target": str(self._sid)})
        except Exception as e:
            log.debug("close_session for %s failed: %s", self._sid, e)


# ============================================================
# Server side
# ============================================================

class ServerTransport:
    """Worker-side transport: accept connections, route to sessions."""

    def __init__(self, listener: Listener) -> None:
        self._listener = listener
        self._sessions: dict[str, ServerSession] = {}
        self._accept_queue: asyncio.Queue[ServerSession] = asyncio.Queue()
        self._router_task: asyncio.Task | None = None
        self._reaper_task: asyncio.Task | None = None

    async def start(self) -> None:
        await self._listener.bind()
        self._router_task = asyncio.create_task(self._router_loop())
        self._reaper_task = asyncio.create_task(self._reaper_loop())

    async def accept_session(self) -> "ServerSession":
        return await self._accept_queue.get()

    async def close(self) -> None:
        if self._router_task:
            self._router_task.cancel()
        if self._reaper_task:
            self._reaper_task.cancel()
        for session in list(self._sessions.values()):
            session._close()
        self._sessions.clear()
        await self._listener.close()

    @property
    def port(self) -> int | None:
        return getattr(self._listener, "port", None)

    # --- internal router ---

    async def _router_loop(self) -> None:
        try:
            while True:
                reader, writer = await self._listener.accept()
                asyncio.create_task(self._handle_connection(reader, writer))
        except asyncio.CancelledError:
            pass

    async def _handle_connection(self, reader, writer) -> None:
        try:
            type_byte = await reader.readexactly(1)
        except (asyncio.IncompleteReadError, OSError):
            writer.close()
            return

        if type_byte == TYPE_RQ:
            ch = FrameChannel(reader, writer)
            await self._handle_rq_channel(ch)
        elif type_byte == TYPE_FRAME:
            await self._handle_frame_connection(reader, writer)
        else:
            log.warning("unknown connection type 0x%02x", type_byte[0])
            writer.close()

    async def _handle_rq_channel(self, ch: FrameChannel) -> None:
        """R/Q loop: read request frames, route, write response frames."""
        try:
            while True:
                req = await ch.recv_msg(Request)
                if req is None:
                    break
                resp = await self._route_request(req, ch)
                if resp is not None:
                    await ch.send_msg(resp)
        except Exception:
            pass
        finally:
            await ch.close()

    async def _route_request(self, req: Request, ch: FrameChannel) -> Response | None:
        session_id = req.id.session

        # Internal protocol: ping
        if req.method == _PING:
            session = self._sessions.get(session_id)
            if session:
                session._last_seen = time.monotonic()
            return Response.ok(req, {"pong": True})

        # Internal protocol: close_session
        if req.method == _CLOSE_SESSION:
            target = req.params.get("target", session_id)
            closed = self._close_session(target)
            return Response.ok(req, {"closed": closed})

        # Get or create session
        session = self._sessions.get(session_id)
        if session is None:
            session = ServerSession(session_id)
            self._sessions[session_id] = session
            await self._accept_queue.put(session)

        session._last_seen = time.monotonic()

        # Internal protocol: open_frame_channel
        if req.method == _OPEN_FRAME_CHANNEL:
            session._pending_frame_ops.add(req.id.seq)
            return Response.ok(req, {"registered": True})

        # Normal request: push to session queue, response sent by dispatch
        await session._enqueue(req, ch)
        return None  # response handled by ServerSession.send_response

    async def _handle_frame_connection(self, reader, writer) -> None:
        try:
            oid = await read_id(reader)
        except (asyncio.IncompleteReadError, OSError):
            writer.close()
            return

        session = self._sessions.get(oid.session)
        if session is None or oid.seq not in session._pending_frame_ops:
            log.warning("frame handshake rejected: %s", oid)
            writer.close()
            return

        session._pending_frame_ops.discard(oid.seq)
        channel = FrameChannel(reader, writer)
        session._frame_channels[oid.seq] = channel
        log.debug("frame channel attached: %s", oid)

    def _close_session(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        session._close()
        log.debug("session %s: closed", session_id)
        return True

    async def _reaper_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(_SESSION_TTL)
                now = time.monotonic()
                stale = [
                    sid for sid, s in self._sessions.items()
                    if (now - s._last_seen) > _SESSION_TTL
                    and s._request_queue.empty()
                ]
                for sid in stale:
                    log.info("session %s: TTL expired, reaping", sid)
                    self._close_session(sid)
        except asyncio.CancelledError:
            pass


class _PendingRequest:
    """A request queued for dispatch, with its R/Q channel for response."""
    __slots__ = ("request", "channel")

    def __init__(self, req: Request, ch: FrameChannel) -> None:
        self.request = req
        self.channel = ch


class ServerSession:
    """Worker-side session: get requests, send responses."""

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._request_queue: asyncio.Queue[_PendingRequest | None] = asyncio.Queue()
        self._pending_frame_ops: set[str] = set()
        self._frame_channels: dict[str, FrameChannel] = {}
        self._last_seen: float = time.monotonic()
        self._closed = False
        self._current_channel: FrameChannel | None = None

    def get_session_id(self) -> str:
        return self._session_id

    async def get_request(self) -> Request | None:
        pending = await self._request_queue.get()
        if pending is None:
            return None
        self._current_channel = pending.channel
        return pending.request

    async def send_response(self, req: Request, result: Any) -> None:
        await self._current_channel.send_msg(Response.ok(req, result))

    async def send_error(self, req: Request, code: ErrorCode, message: str) -> None:
        await self._current_channel.send_msg(Response.fail(req, code, message))

    def get_frame_channel(self, seq: str) -> FrameChannel | None:
        return self._frame_channels.get(seq)

    async def _enqueue(self, req: Request, ch: FrameChannel) -> None:
        await self._request_queue.put(_PendingRequest(req, ch))

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._request_queue.put_nowait(None)
        for ch in self._frame_channels.values():
            if not ch.closed:
                asyncio.ensure_future(ch.close())
        self._frame_channels.clear()
        self._pending_frame_ops.clear()
