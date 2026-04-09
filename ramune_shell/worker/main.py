"""Worker daemon entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging

from ramune_shell.worker.config import WorkerConfig
from ramune_shell.worker.server import WorkerServer

import ramune_shell.worker.handlers  # noqa: F401 — built-in commands
from ramune_shell.worker.features import exec as _exec_feature

log = logging.getLogger(__name__)


def main(config: WorkerConfig | None = None) -> None:
    if config is None:
        config = WorkerConfig()

    logging.basicConfig(level=logging.DEBUG)

    # Register features
    _exec_feature.register()
    log.info("features registered")

    server = WorkerServer(host=config.host, port=config.port)
    asyncio.run(server.serve())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ramune-shell worker daemon")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9800)
    args = parser.parse_args()

    config = WorkerConfig(host=args.host, port=args.port)
    main(config)
