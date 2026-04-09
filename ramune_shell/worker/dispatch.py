"""Request dispatch: built-in commands and plugin tools."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from ramune_shell.protocol import Request, Response, ErrorCode
from ramune_shell.protocol.commands import (
    Method,
    PluginInvocation,
    command_from_params,
)

log = logging.getLogger(__name__)

# Built-in command handlers: Method -> async fn(Command) -> result
_HANDLERS: dict[Method, Callable] = {}

# Plugin handlers: tool_name -> async fn(params: dict) -> result
_PLUGIN_HANDLERS: dict[str, Callable] = {}

# Loaded modules: module_name -> list of tool names
_MODULES: dict[str, list[str]] = {}

# Running tasks: request_id -> asyncio.Task (for cancellation)
_RUNNING: dict[str, asyncio.Task] = {}


def handler(method: Method):
    """Decorator to register a built-in command handler."""
    def decorator(fn: Callable) -> Callable:
        _HANDLERS[method] = fn
        return fn
    return decorator


def register_module(module: str, handlers: dict[str, Callable]) -> None:
    """Register a feature module with its handlers."""
    _PLUGIN_HANDLERS.update(handlers)
    _MODULES[module] = list(handlers.keys())
    log.info("module '%s' registered: %s", module, list(handlers.keys()))


def get_modules() -> dict[str, list[str]]:
    """Return loaded modules and their tools."""
    return dict(_MODULES)


def cancel_request(request_id: str) -> bool:
    task = _RUNNING.get(request_id)
    if task is None:
        return False
    task.cancel()
    return True


async def dispatch(req: Request) -> Response:
    try:
        if PluginInvocation.is_plugin_method(req.method):
            return await _dispatch_plugin(req)
        else:
            return await _dispatch_command(req)
    except Exception as e:
        log.exception("dispatch error for %s", req.method)
        return Response.fail(req.id, ErrorCode.INTERNAL_ERROR, str(e))


async def _dispatch_command(req: Request) -> Response:
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
    invocation = PluginInvocation.from_method(req.method, req.params)
    handler_fn = _PLUGIN_HANDLERS.get(invocation.tool_name)
    if handler_fn is None:
        return Response.fail(
            req.id, ErrorCode.METHOD_NOT_FOUND,
            f"feature '{invocation.tool_name}' not available on this worker",
        )

    handler_task = asyncio.create_task(handler_fn(invocation.params))
    _RUNNING[req.id] = handler_task
    try:
        result = await handler_task
        return Response.ok(req.id, result)
    except asyncio.CancelledError:
        return Response.fail(req.id, ErrorCode.CANCELLED, "cancelled")
    finally:
        _RUNNING.pop(req.id, None)
