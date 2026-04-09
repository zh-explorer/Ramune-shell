"""Worker daemon entry point."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ramune_shell_worker.server import WorkerServer
from ramune_shell_worker.plugins import discover_plugins
from ramune_shell_worker.dispatch import register_plugins

import ramune_shell_worker.handlers  # noqa: F401 — register built-in handlers

log = logging.getLogger(__name__)

DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parents[3] / "plugins"


def main(
    host: str = "127.0.0.1",
    port: int = 9800,
    plugins_dir: Path | None = None,
) -> None:
    """Start the worker daemon."""
    logging.basicConfig(level=logging.DEBUG)

    if plugins_dir is None:
        plugins_dir = DEFAULT_PLUGINS_DIR

    # Discover and register plugins
    tools, handler_map = discover_plugins(plugins_dir)
    meta_map = {t["name"]: t for t in tools}
    register_plugins(handler_map, meta_map)
    log.info("loaded %d plugin tools", len(tools))

    # Start server
    server = WorkerServer(host=host, port=port)
    asyncio.run(server.serve())


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9800)
    parser.add_argument("--plugins-dir", type=Path, default=None)
    args = parser.parse_args()
    main(host=args.host, port=args.port, plugins_dir=args.plugins_dir)
