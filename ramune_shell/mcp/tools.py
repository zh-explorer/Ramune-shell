"""Built-in MCP tool implementations."""

from __future__ import annotations

import asyncio
from typing import Annotated

from pydantic import Field
from mcp.server.fastmcp import FastMCP

from ramune_shell.mcp.hosts import HostManager
from ramune_shell.mcp.executor import TaskExecutor
from ramune_shell.mcp.output import OutputStore

PING_TIMEOUT = 10.0


def register_builtin_tools(
    mcp_server: FastMCP,
    host_manager: HostManager,
    executor: TaskExecutor,
    output_store: OutputStore,
    pending_results: dict,
) -> None:

    # --- host management ---

    @mcp_server.tool(description="Register a TCP worker (dev mode, no auth).")
    async def host_add(name: str, host: str, port: int = 9800) -> dict:
        info = host_manager.add(name, host, port)
        return {"added": info.model_dump()}

    @mcp_server.tool(description="Register an SSH worker.")
    async def ssh_host_add(
        name: str,
        alias: str | None = None,
        host: str = "",
        ssh_port: int = 22,
        user: str = "",
        key_filename: str | None = None,
        password: str | None = None,
        worker_port: Annotated[int, Field(description="Worker daemon listen port")] = 9800,
    ) -> dict:
        try:
            info = await host_manager.add_ssh(
                name=name, worker_port=worker_port, alias=alias,
                host=host, port=ssh_port, user=user,
                key_filename=key_filename, password=password,
            )
            return {"added": info.model_dump()}
        except Exception as e:
            return {"error": str(e)}

    @mcp_server.tool(description="Remove a registered host.")
    async def host_remove(name: str) -> dict:
        removed = await host_manager.remove(name)
        return {"removed": removed, "name": name}

    @mcp_server.tool(description="List registered hosts.")
    async def host_list() -> dict:
        return {"hosts": host_manager.list()}

    # --- worker interaction ---

    @mcp_server.tool(description="Ping remote worker.")
    async def ping(host: str) -> dict:
        try:
            transport = host_manager.get_transport(host)
            session = await transport.open_session()
            try:
                ok = await asyncio.wait_for(session.ping(), timeout=PING_TIMEOUT)
                return {"pong": ok}
            finally:
                await session.close()
        except asyncio.TimeoutError:
            return {"error": "ping timeout"}
        except Exception as e:
            return {"error": str(e)}

    @mcp_server.tool(description="List features registered on remote worker.")
    async def list_features(host: str) -> dict:
        transport = host_manager.get_transport(host)
        session = await transport.open_session()
        try:
            resp = await session.request("list_features", {})
            if resp.error:
                return {"error": resp.error.message}
            return resp.result
        except Exception as e:
            return {"error": str(e)}
        finally:
            await session.close()

    # --- task management ---

    @mcp_server.tool(description="Poll async task result.")
    async def get_result(task_id: str) -> dict:
        task = pending_results.get(task_id)
        if task is None:
            return {"task_id": task_id, "status": "not_found"}
        if not task.is_done:
            return {"task_id": task_id, "status": task.status.value}
        # Done — return result and remove
        result = task.to_dict()
        if "result" in result:
            result["result"] = output_store.limit(result["result"])
        del pending_results[task_id]
        return result

    @mcp_server.tool(description="Cancel a running task.")
    async def cancel_task(task_id: str) -> dict:
        task = pending_results.get(task_id)
        if task is None:
            # Maybe still in executor's active queue
            cancelled = executor.cancel(task_id)
            if cancelled:
                return {"task_id": task_id, "status": "cancelled"}
            return {"task_id": task_id, "status": "not_found"}
        if task.is_done:
            return task.to_dict()
        executor.cancel(task_id)
        del pending_results[task_id]
        return {"task_id": task_id, "status": "cancelled"}
