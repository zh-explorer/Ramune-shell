"""Worker daemon entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from ramune_shell_worker.config import WorkerConfig
from ramune_shell_worker.server import WorkerServer
from ramune_shell_worker.plugins import discover_plugins
from ramune_shell_worker.dispatch import register_plugins

import ramune_shell_worker.handlers  # noqa: F401

log = logging.getLogger(__name__)

DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parents[3] / "plugins"


def main(config: WorkerConfig | None = None) -> None:
    """Start the worker daemon."""
    if config is None:
        config = WorkerConfig()

    logging.basicConfig(level=logging.DEBUG)

    plugins_dir = Path(config.plugins_dir) if config.plugins_dir else DEFAULT_PLUGINS_DIR
    tools, handler_map = discover_plugins(plugins_dir)
    meta_map = {t["name"]: t for t in tools}
    register_plugins(handler_map, meta_map)
    log.info("loaded %d plugin tools", len(tools))

    server = WorkerServer(host=config.host, port=config.port)
    asyncio.run(server.serve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ramune-shell worker daemon")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9800)
    parser.add_argument("--plugins-dir", default="")
    args = parser.parse_args()

    config = WorkerConfig(
        host=args.host,
        port=args.port,
        plugins_dir=args.plugins_dir,
    )
    main(config)
