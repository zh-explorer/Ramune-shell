"""Ramune-shell shared protocol.

Wire format and shared types for communication between MCP Server and
remote Client daemon.  Serialized with msgpack over TCP (SSH channel
or direct socket in dev mode).
"""

from ramune_shell_protocol.messages import Request, Response, ErrorCode, ErrorInfo

__all__ = [
    "Request",
    "Response",
    "ErrorCode",
    "ErrorInfo",
]
