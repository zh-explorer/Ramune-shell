"""Ramune-shell shared protocol.

Wire format and shared types for communication between MCP Server and
remote Client daemon.  Serialized with msgpack over TCP (SSH channel
or direct socket in dev mode).
"""

from ramune_shell_protocol.messages import Request, Response, ErrorCode, ErrorInfo
from ramune_shell_protocol.channel import (
    TYPE_RQ, TYPE_FRAME,
    write_frame, read_frame, write_token, read_token,
    FrameChannel,
)

__all__ = [
    "Request",
    "Response",
    "ErrorCode",
    "ErrorInfo",
    "TYPE_RQ",
    "TYPE_FRAME",
    "write_frame",
    "read_frame",
    "write_token",
    "read_token",
    "FrameChannel",
]
