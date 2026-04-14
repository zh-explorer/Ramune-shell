"""Worker daemon entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging

from ramune_shell.worker.config import WorkerConfig
from ramune_shell.transport import TcpListener, ServerTransport
from ramune_shell.worker.dispatch import handle_session
from ramune_shell.worker.handlers import register_builtins
from ramune_shell.features.exec import register_worker as register_exec

log = logging.getLogger(__name__)


async def serve(config: WorkerConfig) -> None:
    register_builtins()
    register_exec()
    log.info("handlers registered")

    listener = TcpListener(host=config.host, port=config.port)
    transport = ServerTransport(listener)
    await transport.start()
    log.info("worker listening on %s:%s", config.host, transport.port)

    try:
        while True:
            session = await transport.accept_session()
            asyncio.create_task(handle_session(session))
    except asyncio.CancelledError:
        pass
    finally:
        await transport.close()


def main(config: WorkerConfig | None = None) -> None:
    if config is None:
        config = WorkerConfig()
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(serve(config))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ramune-shell worker daemon")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9800)
    args = parser.parse_args()
    main(WorkerConfig(host=args.host, port=args.port))
