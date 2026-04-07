"""MCP server application."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ramune_shell_mcp.connector import WorkerConnector
from ramune_shell_mcp.plugins import discover_metadata, register_plugin_tools

mcp = FastMCP("ramune-shell")

DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parents[3] / "plugins"

# Host -> connector mapping (will be replaced by proper host management later)
_connectors: dict[str, WorkerConnector] = {}


def get_connector(host: str = "default") -> WorkerConnector:
    if host not in _connectors:
        _connectors[host] = WorkerConnector()
    return _connectors[host]


# Built-in tools
@mcp.tool()
async def ping(host: str = "default") -> dict:
    """Ping the remote worker to check connectivity."""
    connector = get_connector(host)
    resp = await connector.call("ping")
    if resp.error:
        return {"error": resp.error.message}
    return resp.result


@mcp.tool()
async def list_plugins(host: str = "default") -> dict:
    """List plugins loaded on the remote worker."""
    connector = get_connector(host)
    resp = await connector.call("list_plugins")
    if resp.error:
        return {"error": resp.error.message}
    return resp.result


# Register plugin tools from metadata
_tools_metadata = discover_metadata(DEFAULT_PLUGINS_DIR)
register_plugin_tools(mcp, _tools_metadata, get_connector)
