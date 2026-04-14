"""MCP server application."""

from __future__ import annotations

from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from ramune_shell.mcp.config import McpConfig
from ramune_shell.mcp.hosts import HostManager
from ramune_shell.mcp.output import OutputStore
from ramune_shell.mcp.executor import TaskExecutor
from ramune_shell.mcp.tools import register_builtin_tools
import ramune_shell.features.exec  # noqa: F401 — registers @feature + RPC
from ramune_shell.mcp.feature import FeatureRuntime, register_all_features


def create_app(config: McpConfig | None = None) -> FastMCP:
    if config is None:
        config = McpConfig()

    output_store = OutputStore(
        max_length=config.output_max_length,
        string_preview=config.output_string_preview,
        list_cap=config.output_list_cap,
        max_files=config.output_max_files,
        output_dir=config.resolved_output_dir,
    )
    host_manager = HostManager()
    executor = TaskExecutor()
    pending_results: dict = {}  # task_id → Task, for async polling

    @asynccontextmanager
    async def lifespan(app):
        yield
        await host_manager.close_all()
        output_store.cleanup()

    server = FastMCP(
        "ramune-shell",
        port=config.port,
        instructions=(
            "Ramune-shell: remote machine control for AI agents. "
            "Use host_add to register a worker, then use host name in other tools. "
            "Long-running calls may return a task_id — use get_result to poll, cancel_task to abort."
        ),
        lifespan=lifespan,
    )

    runtime = FeatureRuntime(executor, host_manager, output_store, pending_results, config.default_timeout)

    register_builtin_tools(server, host_manager, executor, output_store, pending_results)
    register_all_features(server, runtime)

    return server


mcp = create_app()
