"""Protocol message types.

Protocol rules:
1. One Request produces exactly one Response, matched by id.
2. Response must arrive within a transport-level timeout;
   exceeding it means the channel is broken (not a business error).
3. Requests are bidirectional — both ends can initiate.
   Business semantics decide who sends what.
4. Each Request is logically an independent channel; no protocol-level
   chunking.  The transport layer handles multiplexing
   (SSH channels or per-request TCP connections in dev mode).
"""

from __future__ import annotations

import asyncio
from enum import IntEnum
from typing import Any, Self

from pydantic import BaseModel, Field

from ramune_shell.protocol.codec import pack, unpack, frame, read_frame, async_read_frame


class Message(BaseModel):
    """Base class with msgpack serialization."""

    def to_bytes(self) -> bytes:
        """Serialize to length-prefixed msgpack."""
        return frame(pack(self.model_dump()))

    @classmethod
    def from_bytes(cls, payload: bytes) -> Self:
        """Deserialize from msgpack payload (without frame header)."""
        return cls.model_validate(unpack(payload))

    @classmethod
    def from_buffer(cls, buf: bytearray) -> tuple[Self | None, int]:
        """Try to read one message from a framed byte buffer."""
        payload, consumed = read_frame(buf)
        if payload is None:
            return None, 0
        return cls.from_bytes(payload), consumed

    @classmethod
    async def async_read(cls, reader: asyncio.StreamReader) -> Self:
        """Read one complete message from an asyncio StreamReader."""
        payload = await async_read_frame(reader)
        return cls.from_bytes(payload)


class ErrorCode(IntEnum):
    UNKNOWN = -1
    INVALID_REQUEST = -2
    METHOD_NOT_FOUND = -3
    INVALID_PARAMS = -4
    INTERNAL_ERROR = -5
    TIMEOUT = -10
    CANCELLED = -11


class ErrorInfo(BaseModel, frozen=True):
    code: int
    message: str


class Request(Message):
    """Bidirectional request — either end can send."""

    id: str
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class Response(Message):
    """Response to a Request, matched by id."""

    id: str
    result: Any = None
    error: ErrorInfo | None = None

    @classmethod
    def ok(cls, req_id: str, result: Any = None) -> Response:
        return cls(id=req_id, result=result)

    @classmethod
    def fail(cls, req_id: str, code: ErrorCode, message: str) -> Response:
        return cls(id=req_id, error=ErrorInfo(code=int(code), message=message))
