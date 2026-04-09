"""Built-in MCP tool implementations."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field
from mcp.server.fastmcp import FastMCP

from ramune_shell_mcp.hosts import HostManager
from ramune_shell_mcp.tasks import TaskManager, next_request_id


def register_builtin_tools(
    mcp_server: FastMCP,
    host_manager: HostManager,
    task_manager: TaskManager,
) -> None:

    async def _call(host: str, method: str):
        connector = host_manager.get_connector(host)
        resp = await connector.call(method, request_id=next_request_id())
        if resp.error:
            return {"error": resp.error.message}
        return resp.result

    # --- host management ---

    @mcp_server.tool(description="Register a TCP worker (dev mode, no auth).")
    async def host_add(name: str, host: str, port: int = 9800) -> dict:
        info = host_manager.add(name, host, port)
        return {"added": info.model_dump()}

    @mcp_server.tool(description="Register an SSH worker. Use alias for ~/.ssh/config, or specify params explicitly.")
    async def ssh_host_add(
        name: str,
        alias: str | None = None,
        host: str = "",
        ssh_port: int = 22,
        user: str = "",
        key_filename: str | None = None,
        password: str | None = None,
        worker_port: Annotated[int, Field(description="Worker daemon listen port on remote machine")] = 9800,
    ) -> dict:
        try:
            info = host_manager.add_ssh(
                name=name,
                worker_port=worker_port,
                alias=alias,
                host=host,
                port=ssh_port,
                user=user,
                key_filename=key_filename,
                password=password,
            )
            return {"added": info.model_dump()}
        except Exception as e:
            return {"error": str(e)}

    @mcp_server.tool(description="Remove a registered host.")
    async def host_remove(name: str) -> dict:
        removed = host_manager.remove(name)
        return {"removed": removed, "name": name}

    @mcp_server.tool(description="List registered hosts.")
    async def host_list() -> dict:
        return {"hosts": host_manager.list()}

    # --- worker interaction ---

    @mcp_server.tool(description="Ping remote worker.")
    async def ping(host: str) -> dict:
        return await _call(host, "ping")

    @mcp_server.tool(description="List plugins on remote worker.")
    async def list_plugins(host: str) -> dict:
        return await task_manager.execute(_call(host, "list_plugins"))

    # --- task management ---

    @mcp_server.tool(description="Poll async task result.")
    async def get_result(task_id: str) -> dict:
        return task_manager.get_result(task_id)

    @mcp_server.tool(description="Cancel a running task.")
    async def cancel_task(task_id: str, host: str | None = None) -> dict:
        result = task_manager.cancel(task_id)
        # Also tell the worker to cancel (task_id == request_id on wire)
        if host:
            try:
                connector = host_manager.get_connector(host)
                await connector.call("cancel", {"request_id": task_id}, request_id=next_request_id())
            except Exception:
                pass  # best-effort
        return result
