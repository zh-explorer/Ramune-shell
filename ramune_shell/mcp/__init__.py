"""Ramune-shell MCP server.

Exports for feature developers:
- feature: decorator to register an MCP-side handler
- ToolContext: injected into handlers, wraps transport session
"""

from ramune_shell.mcp.feature import feature, ToolContext

__all__ = ["feature", "ToolContext"]
