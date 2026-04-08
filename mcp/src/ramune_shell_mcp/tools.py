"""Built-in MCP tool implementations."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ramune_shell_mcp.tasks import TaskManager


def register_builtin_tools(
    mcp_server: FastMCP,
    get_connector,
    task_manager: TaskManager,
) -> None:

    async def _call(host: str, method: str):
        connector = get_connector(host)
        resp = await connector.call(method)
        if resp.error:
            return {"error": resp.error.message}
        return resp.result

    @mcp_server.tool(description="Ping remote worker.")
    async def ping(host: str) -> dict:
        return await _call(host, "ping")

    @mcp_server.tool(description="List plugins on remote worker.")
    async def list_plugins(host: str) -> dict:
        return await task_manager.execute(_call(host, "list_plugins"))

    @mcp_server.tool(description="Poll async task result.")
    async def get_result(task_id: str) -> dict:
        return task_manager.get_result(task_id)

    @mcp_server.tool(description="Cancel a running task.")
    async def cancel_task(task_id: str) -> dict:
        return task_manager.cancel(task_id)
