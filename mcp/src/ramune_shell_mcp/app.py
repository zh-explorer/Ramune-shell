"""MCP server application."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ramune_shell_mcp.config import McpConfig
from ramune_shell_mcp.hosts import HostManager
from ramune_shell_mcp.output import OutputStore
from ramune_shell_mcp.plugins import discover_metadata, register_plugin_tools
from ramune_shell_mcp.tasks import TaskManager
from ramune_shell_mcp.tools import register_builtin_tools

DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parents[3] / "plugins"


def create_app(config: McpConfig | None = None) -> FastMCP:
    """Create and configure the MCP server."""
    if config is None:
        config = McpConfig()

    server = FastMCP(
        "ramune-shell",
        port=config.port,
        instructions=(
            "Ramune-shell: remote machine control for AI agents. "
            "Use host_add to register a worker, then use host name in other tools. "
            "Long-running calls may return a task_id — use get_result to poll, cancel_task to abort."
        ),
    )

    output_store = OutputStore(
        max_length=config.output_max_length,
        string_preview=config.output_string_preview,
        list_cap=config.output_list_cap,
        max_files=config.output_max_files,
        output_dir=config.resolved_output_dir,
    )
    host_manager = HostManager()
    task_manager = TaskManager(default_timeout=config.default_timeout, output_store=output_store)

    def get_connector(host: str):
        return host_manager.get_connector(host)

    register_builtin_tools(server, host_manager, task_manager)

    plugins_dir = config.plugins_dir or str(DEFAULT_PLUGINS_DIR)
    tools_metadata = discover_metadata(Path(plugins_dir))
    register_plugin_tools(server, tools_metadata, get_connector, task_manager)

    return server


# Default app instance
mcp = create_app()
