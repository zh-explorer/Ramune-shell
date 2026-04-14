"""FrameChannel: the unified transport unit.

Wire format: [4-byte big-endian length][payload]

FrameChannel provides two levels of API:
- Low-level: send(bytes) / recv() -> bytes (raw frames)
- High-level: send_msg(Message) / recv_msg(cls) -> Message (typed)

All transport communication goes through FrameChannel.
Codec (msgpack) and framing are internal implementation details.
"""

from __future__ import annotations

import asyncio
import struct
from typing import Any, TypeVar

import msgpack

from ramune_shell.transport.addr import OpId

_HEADER = struct.Struct(">I")

# Type bytes: first byte on each new TCP connection
TYPE_RQ = b"\x01"
TYPE_FRAME = b"\x02"

T = TypeVar("T")


# --- internal codec (not exported) ---

def _pack(data: dict[str, Any]) -> bytes:
    return msgpack.packb(data, use_bin_type=True)


def _unpack(payload: bytes) -> dict[str, Any]:
    return msgpack.unpackb(payload, raw=False)


# --- handshake helpers (internal, used by session.py) ---

async def write_id(writer: asyncio.StreamWriter, oid: OpId) -> None:
    """Write an OpId handshake frame directly to a raw writer.
    Used before FrameChannel is constructed (during frame connection setup).
    """
    payload = _pack(oid.model_dump())
    writer.write(_HEADER.pack(len(payload)) + payload)
    await writer.drain()


async def read_id(reader: asyncio.StreamReader) -> OpId:
    """Read an OpId handshake frame directly from a raw reader."""
    header = await reader.readexactly(_HEADER.size)
    (length,) = _HEADER.unpack(header)
    payload = await reader.readexactly(length)
    return OpId.model_validate(_unpack(payload))


# --- FrameChannel ---

class FrameChannel:
    """Full-duplex framed channel over a TCP connection.

    Low-level API (raw bytes):
        await ch.send(b"hello")
        data = await ch.recv()  # -> bytes | None

    High-level API (typed messages):
        await ch.send_msg(request)
        resp = await ch.recv_msg(Response)  # -> Response | None
    """

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer
        self._buf = bytearray()
        self._closed = False

    # --- low-level: raw bytes ---

    async def send(self, data: bytes) -> None:
        """Send a raw frame."""
        self._writer.write(_HEADER.pack(len(data)) + data)
        await self._writer.drain()

    async def recv(self) -> bytes | None:
        """Receive a raw frame. Returns None on EOF/error. Cancellable."""
        f = self._extract_frame()
        if f is not None:
            return f
        try:
            while True:
                data = await self._reader.read(0x1000)
                if not data:
                    self._closed = True
                    return None
                self._buf.extend(data)
                f = self._extract_frame()
                if f is not None:
                    return f
        except (OSError, ConnectionError):
            self._closed = True
            return None

    # --- high-level: typed messages ---

    async def send_msg(self, msg) -> None:
        """Send a pydantic Message (Request/Response) as a frame."""
        await self.send(_pack(msg.model_dump()))

    async def recv_msg(self, cls: type[T]) -> T | None:
        """Receive and deserialize a pydantic Message. Returns None on EOF."""
        data = await self.recv()
        if data is None:
            return None
        return cls.model_validate(_unpack(data))

    # --- lifecycle ---

    def detach(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Consume the channel, returning the raw reader/writer.

        The FrameChannel becomes unusable after this call. Use this to
        hand the underlying connection to another framework, protocol,
        or subprocess.

        Raises RuntimeError if there is unprocessed data in the internal
        buffer. Callers must ensure the stream is clean (all frames fully
        consumed) before detaching.
        """
        if self._closed:
            raise RuntimeError("channel is closed")
        if self._buf:
            raise RuntimeError(
                f"cannot detach: {len(self._buf)} bytes of unprocessed data in buffer"
            )
        reader, writer = self._reader, self._writer
        self._reader = None  # type: ignore
        self._writer = None  # type: ignore
        self._closed = True
        return reader, writer

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._writer and not self._writer.is_closing():
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass

    @property
    def closed(self) -> bool:
        return self._closed

    async def __aenter__(self) -> FrameChannel:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    # --- internal ---

    def _extract_frame(self) -> bytes | None:
        if len(self._buf) < _HEADER.size:
            return None
        (length,) = _HEADER.unpack_from(self._buf, 0)
        total = _HEADER.size + length
        if len(self._buf) < total:
            return None
        data = bytes(self._buf[_HEADER.size:total])
        del self._buf[:total]
        return data
