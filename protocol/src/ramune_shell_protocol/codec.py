"""Msgpack wire framing.

Wire format: [4-byte big-endian length][msgpack payload]

Length-prefixed framing allows clean message boundaries over a TCP stream.
"""

from __future__ import annotations

import asyncio
import struct
from typing import Any

import msgpack


HEADER = struct.Struct(">I")  # 4-byte big-endian unsigned int


def pack(data: dict[str, Any]) -> bytes:
    """Serialize a dict to msgpack bytes."""
    return msgpack.packb(data, use_bin_type=True)


def unpack(payload: bytes) -> dict[str, Any]:
    """Deserialize msgpack bytes to a dict."""
    return msgpack.unpackb(payload, raw=False)


def frame(payload: bytes) -> bytes:
    """Add length-prefix framing to a payload."""
    return HEADER.pack(len(payload)) + payload


def read_frame(buf: bytearray) -> tuple[bytes | None, int]:
    """Try to read one frame from a byte buffer.

    Returns (payload, consumed_bytes).  If the buffer doesn't contain
    a complete frame yet, returns (None, 0).
    """
    if len(buf) < HEADER.size:
        return None, 0
    (length,) = HEADER.unpack_from(buf, 0)
    total = HEADER.size + length
    if len(buf) < total:
        return None, 0
    payload = bytes(buf[HEADER.size:total])
    return payload, total


async def async_read_frame(reader: asyncio.StreamReader) -> bytes:
    """Read one complete frame from an asyncio StreamReader.

    Raises asyncio.IncompleteReadError if the connection closes mid-frame.
    """
    header = await reader.readexactly(HEADER.size)
    (length,) = HEADER.unpack(header)
    payload = await reader.readexactly(length)
    return payload
