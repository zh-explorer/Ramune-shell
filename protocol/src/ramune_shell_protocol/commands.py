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


# method name -> Command class
COMMAND_TYPES: dict[str, type[Command]] = {
    cmd.method.value: cmd
    for cmd in [Ping, Shutdown, ListPlugins]
}


def command_from_params(method: str, params: dict[str, Any]) -> Command:
    """Reconstruct a typed Command from wire method + params."""
    cls = COMMAND_TYPES.get(method)
    if cls is None:
        raise ValueError(f"unknown built-in method: {method}")
    return cls.model_validate(params)
