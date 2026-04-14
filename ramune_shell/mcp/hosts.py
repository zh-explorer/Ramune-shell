"""Host management for remote workers."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from ramune_shell.transport import ClientTransport, TcpConnector
from ramune_shell.transport.ssh import SshConnector, SshConfig

log = logging.getLogger(__name__)


class HostInfo(BaseModel):
    """Registered host metadata."""

    name: str
    host: str
    port: int = 9800
    type: str = "tcp"

    extra: dict[str, Any] = {}


class HostManager:
    """Manages registered hosts and their transports."""

    def __init__(self) -> None:
        self._hosts: dict[str, HostInfo] = {}
        self._transports: dict[str, ClientTransport] = {}
        self._ssh_connectors: dict[str, SshConnector] = {}

    # --- TCP host (dev mode) ---

    def add(self, name: str, host: str, port: int = 9800, **extra) -> HostInfo:
        info = HostInfo(name=name, host=host, port=port, type="tcp", extra=extra)
        self._hosts[name] = info
        self._transports[name] = ClientTransport(TcpConnector(host, port))
        return info

    # --- SSH host ---

    async def add_ssh(
        self,
        name: str,
        worker_port: int = 9800,
        alias: str | None = None,
        host: str = "",
        port: int = 22,
        user: str = "",
        key_filename: str | None = None,
        password: str | None = None,
        **extra,
    ) -> HostInfo:
        config = SshConfig(
            host=host, port=port, user=user,
            key_filename=key_filename, password=password,
            alias=alias,
        )
        ssh_connector = SshConnector(config, worker_port=worker_port)
        await ssh_connector.start()

        display_host = alias or host
        info = HostInfo(
            name=name, host=display_host, port=worker_port,
            type="ssh", extra=extra,
        )
        self._hosts[name] = info
        self._transports[name] = ClientTransport(ssh_connector)
        self._ssh_connectors[name] = ssh_connector
        return info

    # --- common ---

    async def remove(self, name: str) -> bool:
        if name not in self._hosts:
            return False
        ssh = self._ssh_connectors.pop(name, None)
        if ssh:
            await ssh.stop()
        transport = self._transports.pop(name, None)
        if transport:
            await transport.close()
        del self._hosts[name]
        return True

    def get_transport(self, name: str) -> ClientTransport:
        transport = self._transports.get(name)
        if transport is None:
            raise KeyError(f"unknown host: {name}")
        return transport

    def get_ssh_connector(self, name: str) -> SshConnector | None:
        return self._ssh_connectors.get(name)

    def list(self) -> list[dict[str, Any]]:
        return [info.model_dump() for info in self._hosts.values()]

    def get(self, name: str) -> HostInfo | None:
        return self._hosts.get(name)

    async def close_all(self) -> None:
        for name in list(self._hosts):
            await self.remove(name)
