"""Protocol message types.

Pure pydantic models. Serialization/deserialization is handled by
FrameChannel.send_msg() / recv_msg(). No framing or codec logic here.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from pydantic import BaseModel, Field

from ramune_shell.transport.addr import OpId


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


class Request(BaseModel):
    """Bidirectional request — either end can send."""

    id: OpId
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class Response(BaseModel):
    """Response to a Request."""

    id: OpId
    result: Any = None
    error: ErrorInfo | None = None

    @classmethod
    def ok(cls, req: Request, result: Any = None) -> "Response":
        return cls(id=req.id, result=result)

    @classmethod
    def fail(cls, req: Request, code: ErrorCode, message: str) -> "Response":
        return cls(id=req.id, error=ErrorInfo(code=int(code), message=message))
