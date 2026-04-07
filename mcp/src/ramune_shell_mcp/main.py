"""MCP server entry point."""

from ramune_shell_mcp.app import mcp

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
