"""MCP server application."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ramune_shell_mcp.connector import WorkerConnector
from ramune_shell_mcp.hosts import HostManager
from ramune_shell_mcp.plugins import discover_metadata, register_plugin_tools
from ramune_shell_mcp.tasks import TaskManager
from ramune_shell_mcp.tools import register_builtin_tools

mcp = FastMCP(
    "ramune-shell",
    port=9900,
    instructions=(
        "Ramune-shell: remote machine control for AI agents. "
        "Use host_add to register a worker, then use host name in other tools. "
        "Long-running calls may return a task_id — use get_result to poll, cancel_task to abort."
    ),
)
host_manager = HostManager()
task_manager = TaskManager(default_timeout=30.0)

DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parents[3] / "plugins"


def get_connector(host: str) -> WorkerConnector:
    return host_manager.get_connector(host)


# Register tools
register_builtin_tools(mcp, host_manager, task_manager)

_tools_metadata = discover_metadata(DEFAULT_PLUGINS_DIR)
register_plugin_tools(mcp, _tools_metadata, get_connector, task_manager)
