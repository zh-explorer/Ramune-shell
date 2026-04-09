"""Built-in command definitions.

Built-in commands are framework-level lifecycle methods (ping, shutdown, etc.).
Plugin tools use the "plugin:" method prefix and are handled separately.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel


class Method(str, Enum):
    """Built-in method names."""

    PING = "ping"
    SHUTDOWN = "shutdown"
    LIST_PLUGINS = "list_plugins"
    CANCEL = "cancel"
    OPEN_SESSION = "open_session"


class Command(BaseModel):
    """Base class for typed built-in commands."""

    method: ClassVar[Method]

    class Result(BaseModel):
        """Override in subclasses to define the result shape."""


class Ping(Command):
    method: ClassVar[Method] = Method.PING

    class Result(BaseModel):
        pong: bool = True


class Shutdown(Command):
    method: ClassVar[Method] = Method.SHUTDOWN

    class Result(BaseModel):
        pass


class ListPlugins(Command):
    method: ClassVar[Method] = Method.LIST_PLUGINS

    class Result(BaseModel):
        plugins: list[dict[str, Any]]


class Cancel(Command):
    method: ClassVar[Method] = Method.CANCEL
    request_id: str

    class Result(BaseModel):
        cancelled: bool


class OpenSession(Command):
    method: ClassVar[Method] = Method.OPEN_SESSION

    class Result(BaseModel):
        session_id: str
        token: str


# method name -> Command class
COMMAND_TYPES: dict[str, type[Command]] = {
    cmd.method.value: cmd
    for cmd in [Ping, Shutdown, ListPlugins, Cancel, OpenSession]
}


class PluginInvocation:
    """Lightweight wrapper for plugin tool calls.

    Not a Command subclass — plugins use raw params dicts
    and the "plugin:" method prefix on the wire.
    """

    PREFIX = "plugin:"

    def __init__(self, tool_name: str, params: dict[str, Any] | None = None) -> None:
        self.tool_name = tool_name
        self.params = params or {}

    @property
    def method(self) -> str:
        return f"{self.PREFIX}{self.tool_name}"

    @classmethod
    def from_method(cls, method: str, params: dict[str, Any]) -> PluginInvocation:
        """Parse a "plugin:xxx" method string into a PluginInvocation."""
        if not method.startswith(cls.PREFIX):
            raise ValueError(f"not a plugin method: {method}")
        tool_name = method[len(cls.PREFIX):]
        return cls(tool_name, params)

    @classmethod
    def is_plugin_method(cls, method: str) -> bool:
        return method.startswith(cls.PREFIX)


def command_from_params(method: str, params: dict[str, Any]) -> Command:
    """Reconstruct a typed Command from wire method + params."""
    cls = COMMAND_TYPES.get(method)
    if cls is None:
        raise ValueError(f"unknown built-in method: {method}")
    return cls.model_validate(params)
