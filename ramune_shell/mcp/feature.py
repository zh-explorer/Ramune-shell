"""Feature registration framework.

@feature decorator registers handlers with MCP. ToolContext wraps
ClientSession for feature developers. FeatureRuntime packages the
shared execution dependencies.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable

from pydantic import BaseModel

from ramune_shell.transport import ClientSession, FrameChannel, Response
from ramune_shell.transport.rpc import get_rpc
from ramune_shell.mcp.executor import Task

log = logging.getLogger(__name__)


def tool_description(meta: dict[str, Any]) -> str:
    desc = meta["description"]
    tags = meta.get("tags", [])
    if tags:
        desc = f"{desc} [{', '.join(tags)}]"
    return desc


class ToolContext:
    """Injected into feature handlers. Thin wrapper over ClientSession."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    @property
    def session_id(self) -> str:
        return self._session.get_session_id()

    async def call(self, method: str, params: dict | None = None) -> Response:
        return await self._session.request(method, params)

    async def call_feature(self, tool_name: str, request_obj: BaseModel) -> BaseModel:
        rpc = get_rpc(tool_name)
        if not isinstance(request_obj, rpc.RequestModel):
            raise TypeError(
                f"feature '{tool_name}' expects {rpc.RequestModel.__name__}, "
                f"got {type(request_obj).__name__}",
            )
        resp = await self._session.request(tool_name, request_obj.model_dump())
        if resp.error is not None:
            raise RuntimeError(f"feature '{tool_name}' failed: {resp.error.message}")
        return rpc.ResultModel.model_validate(resp.result)

    async def open_frame_channel(self) -> FrameChannel:
        return await self._session.open_frame_channel()

    async def close(self) -> None:
        await self._session.close()


class FeatureRuntime:
    """Shared execution dependencies for all features."""

    def __init__(self, executor, host_manager, output_store,
                 pending_results: dict, default_timeout: float) -> None:
        self._executor = executor
        self._host_manager = host_manager
        self._output_store = output_store
        self._pending_results = pending_results
        self._default_timeout = default_timeout

    async def run(self, handler: Callable, host: str, meta: dict, **kwargs) -> dict:
        """Open session → package Task → submit → wait/timeout."""
        transport = self._host_manager.get_transport(host)
        session = await transport.open_session()
        task_id = session.get_session_id()
        group = meta.get("concurrency_group")

        async def _run():
            ctx = ToolContext(session)
            try:
                return await handler(ctx, **kwargs)
            finally:
                try:
                    await asyncio.shield(asyncio.wait_for(ctx.close(), timeout=60.0))
                except Exception:
                    pass

        task = Task(task_id, _run)
        self._executor.submit(task, host=host, group=group)
        try:
            await task.wait(timeout=self._default_timeout)
            result = task.result
            return self._output_store.limit(result) if isinstance(result, dict) else result
        except asyncio.TimeoutError:
            self._pending_results[task_id] = task
            return {
                "task_id": task_id,
                "status": "running",
                "notice": "Request is still running. Use get_result to poll.",
            }


class _Feature:
    def __init__(self, meta: dict[str, Any], handler: Callable) -> None:
        self.meta = meta
        self.handler = handler

    def register(self, mcp_server, runtime: FeatureRuntime) -> None:
        desc = tool_description(self.meta)
        handler = self.handler
        meta = self.meta
        orig_sig = inspect.signature(handler)
        orig_params = list(orig_sig.parameters.values())
        new_params = [
            inspect.Parameter("host", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str),
        ] + orig_params[1:]
        new_sig = inspect.Signature(new_params, return_annotation=dict)

        async def _tool_fn(**kwargs):
            host = kwargs.pop("host")
            return await runtime.run(handler, host, meta, **kwargs)

        _tool_fn.__name__ = self.meta["name"]
        _tool_fn.__qualname__ = self.meta["name"]
        _tool_fn.__signature__ = new_sig
        mcp_server.tool(description=desc)(_tool_fn)


_features: list[_Feature] = []


def feature(meta: dict[str, Any]) -> Callable:
    def decorator(fn: Callable) -> _Feature:
        f = _Feature(meta, fn)
        _features.append(f)
        return f
    return decorator


def register_all_features(mcp_server, runtime: FeatureRuntime) -> None:
    for f in _features:
        f.register(mcp_server, runtime)
