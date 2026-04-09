"""Request dispatch: built-in commands and plugin tools."""

from __future__ import annotations

import logging
from typing import Any, Callable

from ramune_shell_protocol import Request, Response, ErrorCode
from ramune_shell_protocol.commands import (
    Method,
    PluginInvocation,
    command_from_params,
)

log = logging.getLogger(__name__)

# Built-in command handlers: Method -> async fn(Command) -> result
_HANDLERS: dict[Method, Callable] = {}

# Plugin handlers: tool_name -> async fn(params: dict) -> result
_PLUGIN_HANDLERS: dict[str, Callable] = {}
_PLUGIN_META: dict[str, dict[str, Any]] = {}


def handler(method: Method):
    """Decorator to register a built-in command handler."""
    def decorator(fn: Callable) -> Callable:
        _HANDLERS[method] = fn
        return fn
    return decorator


def register_plugins(
    handler_map: dict[str, Callable],
    meta_map: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Register plugin handlers and metadata."""
    _PLUGIN_HANDLERS.update(handler_map)
    if meta_map:
        _PLUGIN_META.update(meta_map)


async def dispatch(req: Request) -> Response:
    """Route a request to the appropriate handler."""
    try:
        if PluginInvocation.is_plugin_method(req.method):
            return await _dispatch_plugin(req)
        else:
            return await _dispatch_command(req)
    except Exception as e:
        log.exception("dispatch error for %s", req.method)
        return Response.fail(req.id, ErrorCode.INTERNAL_ERROR, str(e))


async def _dispatch_command(req: Request) -> Response:
    """Dispatch a built-in command."""
    try:
        cmd = command_from_params(req.method, req.params)
    except ValueError:
        return Response.fail(
            req.id, ErrorCode.METHOD_NOT_FOUND,
            f"unknown method: {req.method}",
        )

    handler_fn = _HANDLERS.get(cmd.method)
    if handler_fn is None:
        return Response.fail(
            req.id, ErrorCode.METHOD_NOT_FOUND,
            f"no handler for: {req.method}",
        )

    result = await handler_fn(cmd)
    return Response.ok(req.id, result)


async def _dispatch_plugin(req: Request) -> Response:
    """Dispatch a plugin tool call."""
    invocation = PluginInvocation.from_method(req.method, req.params)
    handler_fn = _PLUGIN_HANDLERS.get(invocation.tool_name)
    if handler_fn is None:
        return Response.fail(
            req.id, ErrorCode.METHOD_NOT_FOUND,
            f"unknown plugin: {invocation.tool_name}",
        )

    result = await handler_fn(invocation.params)
    return Response.ok(req.id, result)
