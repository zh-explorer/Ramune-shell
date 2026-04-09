"""Feature registration framework.

Provides @feature decorator, ToolContext, and signature verification.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from ramune_shell.protocol import Response
from ramune_shell.protocol.commands import PluginInvocation
from ramune_shell.mcp.tasks import TaskManager, next_request_id


# --- tool description ---

def tool_description(meta: dict[str, Any]) -> str:
    """Build MCP tool description from metadata, appending tags."""
    desc = meta["description"]
    tags = meta.get("tags", [])
    if tags:
        desc = f"{desc} [{', '.join(tags)}]"
    return desc


# --- signature verification ---

def verify_tool_signature(mcp_server: FastMCP, meta: dict[str, Any]) -> list[str]:
    """Verify a registered MCP tool matches its META definition.

    Returns list of errors (empty = OK).
    """
    errors = []
    name = meta["name"]

    tool = mcp_server._tool_manager._tools.get(name)
    if tool is None:
        return [f"tool '{name}' not registered"]

    schema = tool.parameters
    props = schema.get("properties", {})
    required = set(schema.get("required", []))

    for pname, pdef in meta.get("params", {}).items():
        if pname not in props:
            errors.append(f"param '{pname}' in META but not in tool schema")
            continue
        if pdef.get("required", False) and pname not in required:
            errors.append(f"param '{pname}' should be required")
        if not pdef.get("required", False) and pname in required:
            errors.append(f"param '{pname}' should be optional")

    for pname in props:
        if pname not in meta.get("params", {}):
            errors.append(f"param '{pname}' in tool schema but not in META")

    return errors


# --- ToolContext ---

class ToolContext:
    """Injected into feature handlers. Carries all framework capabilities."""

    def __init__(self, task_id: str, connector) -> None:
        self.task_id = task_id
        self.connector = connector

    async def call(self, method: str, params: dict | None = None) -> Response:
        return await self.connector.call(method, params, request_id=self.task_id)

    async def call_plugin(self, tool_name: str, params: dict | None = None) -> Response:
        invocation = PluginInvocation(tool_name, params or {})
        return await self.call(invocation.method, invocation.params)

    async def open_session(self):
        from ramune_shell.mcp.session import open_session
        return await open_session(self.connector)


# --- @feature decorator ---

class _Feature:
    def __init__(self, meta: dict[str, Any], handler: Callable) -> None:
        self.meta = meta
        self.handler = handler

    def register(self, mcp_server, get_connector, task_manager: TaskManager) -> None:
        desc = tool_description(self.meta)
        handler = self.handler

        orig_sig = inspect.signature(handler)
        orig_params = list(orig_sig.parameters.values())

        new_params = [
            inspect.Parameter("host", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str),
        ] + orig_params[1:]  # skip ctx

        new_sig = inspect.Signature(new_params, return_annotation=dict)

        async def _tool_fn(**kwargs):
            host = kwargs.pop("host")

            def _make_coro(task_id):
                async def _do():
                    connector = get_connector(host)
                    ctx = ToolContext(task_id=task_id, connector=connector)
                    return await handler(ctx, **kwargs)
                return _do()

            return await task_manager.execute(_make_coro)

        _tool_fn.__name__ = self.meta["name"]
        _tool_fn.__qualname__ = self.meta["name"]
        _tool_fn.__signature__ = new_sig

        mcp_server.tool(description=desc)(_tool_fn)


_features: list[_Feature] = []


def feature(meta: dict[str, Any]) -> Callable:
    """Decorator to register a feature handler."""
    def decorator(fn: Callable) -> _Feature:
        f = _Feature(meta, fn)
        _features.append(f)
        return f
    return decorator


def register_all_features(mcp_server, get_connector, task_manager: TaskManager) -> None:
    """Register all @feature-decorated handlers as MCP tools."""
    for f in _features:
        f.register(mcp_server, get_connector, task_manager)
