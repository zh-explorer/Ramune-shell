"""MCP server application."""

from __future__ import annotations

from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from ramune_shell.mcp.config import McpConfig
from ramune_shell.mcp.hosts import HostManager
from ramune_shell.mcp.output import OutputStore
from ramune_shell.mcp.tasks import TaskManager
from ramune_shell.mcp.tools import register_builtin_tools
import ramune_shell.mcp.features.exec  # noqa: F401 — registers via @feature
from ramune_shell.mcp.feature import register_all_features


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
    task_manager = TaskManager(default_timeout=config.default_timeout, output_store=output_store)

    @asynccontextmanager
    async def lifespan(app):
        # startup
        yield
        # shutdown
        await host_manager.close_all()
        task_manager.cleanup()

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

    def get_connector(host: str):
        return host_manager.get_connector(host)

    register_builtin_tools(server, host_manager, task_manager)
    register_all_features(server, get_connector, task_manager)

    return server


mcp = create_app()
