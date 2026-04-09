"""Host management for remote workers."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from pydantic import BaseModel

from ramune_shell.mcp.connector import WorkerConnector
from ramune_shell.mcp.ssh.session import SshSession, SshConfig

log = logging.getLogger(__name__)


class Callable(Protocol):
    """Async callable that sends a request to a worker."""

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any: ...


class HostInfo(BaseModel):
    """Registered host metadata."""

    name: str
    host: str
    port: int = 9800
    type: str = "tcp"  # "tcp" or "ssh"

    # Runtime state
    online: bool = False

    # Extensible metadata (OS, arch, etc.)
    extra: dict[str, Any] = {}


class HostManager:
    """Manages registered hosts and their connectors."""

    def __init__(self) -> None:
        self._hosts: dict[str, HostInfo] = {}
        self._connectors: dict[str, WorkerConnector] = {}
        self._ssh_sessions: dict[str, SshSession] = {}

    # --- TCP host (dev mode) ---

    def add(self, name: str, host: str, port: int = 9800, **extra) -> HostInfo:
        info = HostInfo(name=name, host=host, port=port, type="tcp", extra=extra)
        self._hosts[name] = info
        self._connectors[name] = WorkerConnector(host=host, port=port)
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
        session = SshSession(config, worker_port=worker_port)
        await session.start()

        display_host = alias or host
        info = HostInfo(
            name=name, host=display_host, port=worker_port,
            type="ssh", extra=extra,
        )
        self._hosts[name] = info
        self._ssh_sessions[name] = session
        # SshSession.call is compatible with WorkerConnector.call
        self._connectors[name] = session  # type: ignore
        return info

    # --- common ---

    async def remove(self, name: str) -> bool:
        if name not in self._hosts:
            return False
        session = self._ssh_sessions.pop(name, None)
        if session:
            await session.stop()
        connector = self._connectors.pop(name, None)
        if connector and hasattr(connector, "close_pool"):
            await connector.close_pool()
        del self._hosts[name]
        return True

    def get_connector(self, name: str):
        """Get connector for a host. Works for both TCP and SSH hosts."""
        connector = self._connectors.get(name)
        if connector is None:
            raise KeyError(f"unknown host: {name}")
        return connector

    def get_ssh_session(self, name: str) -> SshSession | None:
        """Get SSH session for a host (None for TCP hosts)."""
        return self._ssh_sessions.get(name)

    def list(self) -> list[dict[str, Any]]:
        return [info.model_dump() for info in self._hosts.values()]

    def get(self, name: str) -> HostInfo | None:
        return self._hosts.get(name)

    async def close_all(self) -> None:
        """Shutdown all hosts. Call on exit."""
        for name in list(self._hosts):
            await self.remove(name)
