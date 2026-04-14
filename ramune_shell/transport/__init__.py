"""Ramune-shell transport layer.

Public API:
- Session: ClientTransport, ClientSession, ServerTransport, ServerSession
- Connection: Connector, Listener, TcpConnector, TcpListener
- Types: FrameChannel, Request, Response
- RPC registry: register_rpc, get_rpc
"""

from ramune_shell.transport.session import (
    ClientTransport,
    ClientSession,
    ServerTransport,
    ServerSession,
)
from ramune_shell.transport.connection import (
    Connector,
    Listener,
    TcpConnector,
    TcpListener,
)
from ramune_shell.transport.channel import FrameChannel
from ramune_shell.transport.messages import Request, Response
from ramune_shell.transport.rpc import register_rpc, get_rpc

__all__ = [
    # Session layer
    "ClientTransport",
    "ClientSession",
    "ServerTransport",
    "ServerSession",
    # Connection layer
    "Connector",
    "Listener",
    "TcpConnector",
    "TcpListener",
    # Types
    "FrameChannel",
    "Request",
    "Response",
    # RPC registry
    "register_rpc",
    "get_rpc",
]
