"""Built-in command handlers."""

from __future__ import annotations

from ramune_shell_protocol.commands import Method, Ping, Shutdown, ListPlugins, Cancel
from ramune_shell_worker.dispatch import handler, cancel_request, _PLUGIN_META


@handler(Method.PING)
async def handle_ping(cmd: Ping):
    return Ping.Result().model_dump()


@handler(Method.SHUTDOWN)
async def handle_shutdown(cmd: Shutdown):
    import asyncio
    loop = asyncio.get_running_loop()
    loop.call_soon(loop.stop)
    return Shutdown.Result().model_dump()


@handler(Method.CANCEL)
async def handle_cancel(cmd: Cancel):
    cancelled = cancel_request(cmd.request_id)
    return Cancel.Result(cancelled=cancelled).model_dump()


@handler(Method.LIST_PLUGINS)
async def handle_list_plugins(cmd: ListPlugins):
    plugins = [
        {"name": name, **meta}
        for name, meta in _PLUGIN_META.items()
    ]
    return ListPlugins.Result(plugins=plugins).model_dump()
