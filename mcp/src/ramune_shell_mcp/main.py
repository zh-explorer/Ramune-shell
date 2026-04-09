"""MCP server entry point."""

from __future__ import annotations

import argparse

from ramune_shell_mcp.config import McpConfig
from ramune_shell_mcp.app import create_app


def main():
    parser = argparse.ArgumentParser(description="Ramune-shell MCP server")
    parser.add_argument("--port", type=int, default=9900)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--plugins-dir", default="")
    parser.add_argument("--transport", default="streamable-http",
                        choices=["stdio", "sse", "streamable-http"])
    args = parser.parse_args()

    config = McpConfig(
        port=args.port,
        default_timeout=args.timeout,
        plugins_dir=args.plugins_dir,
    )
    app = create_app(config)
    app.run(transport=args.transport)


if __name__ == "__main__":
    main()
