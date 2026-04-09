"""Connection channel types and framing.

Every new connection starts with a 1-byte type identifier:
  0x01  R/Q   — request-response loop, connection pooled
  0x02  Frame — length-prefixed framed channel (session data)
"""

from __future__ import annotations

import asyncio
import struct

import msgpack

# Channel type identifiers (first byte of every new connection)
TYPE_RQ = b"\x01"
TYPE_FRAME = b"\x02"

# Frame header for data framing
_FRAME_HEADER = struct.Struct(">I")  # 4-byte big-endian length


# --- low-level frame I/O ---

async def write_frame(writer: asyncio.StreamWriter, data: bytes) -> None:
    """Write a length-prefixed frame."""
    writer.write(_FRAME_HEADER.pack(len(data)) + data)
    await writer.drain()


async def read_frame(reader: asyncio.StreamReader) -> bytes:
    """Read a length-prefixed frame."""
    header = await reader.readexactly(_FRAME_HEADER.size)
    (length,) = _FRAME_HEADER.unpack(header)
    return await reader.readexactly(length)


async def write_token(writer: asyncio.StreamWriter, token: str) -> None:
    """Write a token as the first frame on a Frame channel."""
    payload = msgpack.packb({"token": token}, use_bin_type=True)
    await write_frame(writer, payload)


async def read_token(reader: asyncio.StreamReader) -> str:
    """Read the token from the first frame on a Frame channel."""
    payload = await read_frame(reader)
    data = msgpack.unpackb(payload, raw=False)
    return data["token"]


# --- FrameChannel class ---

class FrameChannel:
    """Full-duplex framed channel over a TCP connection.

    Uses an internal read buffer. recv() blocks at reader.read()
    which is cancellable. try_recv() is non-blocking, only checks
    the buffer. TCP buffer provides backpressure naturally.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._buf = bytearray()
        self._closed = False

    async def send(self, data: bytes) -> None:
        """Send a frame."""
        await write_frame(self._writer, data)

    async def recv(self) -> bytes | None:
        """Receive a frame. Blocks until available. Returns None on EOF.

        Cancellable — the only await point is reader.read().
        """
        frame = self._extract_frame()
        if frame is not None:
            return frame
        while True:
            data = await self._reader.read(65536)
            if not data:
                self._closed = True
                return None
            self._buf.extend(data)
            frame = self._extract_frame()
            if frame is not None:
                return frame

    def _extract_frame(self) -> bytes | None:
        """Try to extract one complete frame from buffer."""
        if len(self._buf) < _FRAME_HEADER.size:
            return None
        (length,) = _FRAME_HEADER.unpack_from(self._buf, 0)
        total = _FRAME_HEADER.size + length
        if len(self._buf) < total:
            return None
        frame = bytes(self._buf[_FRAME_HEADER.size:total])
        del self._buf[:total]
        return frame

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._writer and not self._writer.is_closing():
            self._writer.close()

    @property
    def closed(self) -> bool:
        return self._closed

    async def __aenter__(self) -> FrameChannel:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()
