"""Worker-side session management.

A session is a single full-duplex FrameChannel.

Lifecycle:
- create() → registers token, starts attach timeout
- attach() → Frame connection arrives, wraps in FrameChannel, session ready
- take() → plugin handler takes ownership, manager forgets it
- Plugin handler uses channel.send/recv, closes with async with

Cleanup:
- Unattached sessions reaped after ATTACH_TIMEOUT
- Attached but untaken sessions with dead channels reaped periodically
- Taken sessions are the plugin's responsibility
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Any

from ramune_shell_protocol.channel import FrameChannel

log = logging.getLogger(__name__)

ATTACH_TIMEOUT = 30.0
CLEANUP_INTERVAL = 10.0


class WorkerSession:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.channel: FrameChannel | None = None
        self.ready = asyncio.Event()

    def get_raw_socket(self):
        """Detach and return the raw socket. Session becomes unusable."""
        transport = self.channel._writer.transport
        sock = transport.get_extra_info('socket')
        sock_dup = sock.dup()
        self.channel._writer.close()
        self.channel = None
        return sock_dup


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, WorkerSession] = {}
        self._tokens: dict[str, str] = {}  # token → session_id
        self._cleanup_task: asyncio.Task | None = None

    def start(self) -> None:
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    def stop(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()

    def create(self) -> dict[str, Any]:
        sid = f"sess-{secrets.token_hex(8)}"
        token = secrets.token_hex(16)

        self._sessions[sid] = WorkerSession(sid)
        self._tokens[token] = sid

        asyncio.get_event_loop().call_later(
            ATTACH_TIMEOUT, self._reap_unattached, sid,
        )

        return {"session_id": sid, "token": token}

    def attach(self, token: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        sid = self._tokens.pop(token, None)
        if sid is None:
            log.warning("unknown session token: %s", token)
            writer.close()
            return

        session = self._sessions.get(sid)
        if session is None:
            writer.close()
            return

        channel = FrameChannel(reader, writer)
        session.channel = channel
        session.ready.set()
        log.debug("session %s: attached", sid)

    def take(self, sid: str) -> WorkerSession | None:
        """Take a session out of the manager. Caller owns its lifecycle."""
        return self._sessions.pop(sid, None)

    def _reap_unattached(self, sid: str) -> None:
        session = self._sessions.get(sid)
        if session and not session.ready.is_set():
            log.warning("session %s: not attached after %ss, reaping", sid, ATTACH_TIMEOUT)
            self._sessions.pop(sid, None)

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL)
            dead = []
            for sid, session in self._sessions.items():
                if session.channel and session.channel.closed:
                    dead.append(sid)
            for sid in dead:
                log.info("session %s: channel dead, cleaning up", sid)
                session = self._sessions.pop(sid, None)
                if session and session.channel:
                    await session.channel.close()


session_manager = SessionManager()
