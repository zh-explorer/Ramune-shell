"""SSH session with asyncssh.

Natively async — no threads, no bridging.
SSH channels are asyncio streams, directly usable for Frame channels.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import asyncssh

from pydantic import BaseModel

from ramune_shell.protocol import (
    Request, Response, ErrorCode, TYPE_RQ, TYPE_FRAME,
    write_token,
)
from ramune_shell.protocol.messages import ErrorInfo

log = logging.getLogger(__name__)


class SshConfig(BaseModel):
    """SSH connection configuration."""

    host: str = ""
    port: int = 22
    user: str = ""
    key_filename: str | None = None
    password: str | None = None
    alias: str | None = None

    def to_connect_kwargs(self) -> dict[str, Any]:
        """Build asyncssh.connect() kwargs."""
        if self.alias:
            return self._resolve_alias()
        result: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "username": self.user or os.getenv("USER", "root"),
            "known_hosts": None,
        }
        if self.key_filename:
            result["client_keys"] = [self.key_filename]
        if self.password:
            result["password"] = self.password
        return result

    def _resolve_alias(self) -> dict[str, Any]:
        """Resolve alias from ~/.ssh/config. asyncssh reads config natively."""
        config_path = os.path.expanduser("~/.ssh/config")
        result: dict[str, Any] = {
            "host": self.alias,
            "known_hosts": None,
            "config": config_path if os.path.exists(config_path) else None,
        }
        if self.user:
            result["username"] = self.user
        if self.port != 22:
            result["port"] = self.port
        if self.key_filename:
            result["client_keys"] = [self.key_filename]
        if self.password:
            result["password"] = self.password
        return result


class SshSession:
    """Async SSH session backed by asyncssh."""

    def __init__(self, config: SshConfig, worker_port: int = 9800) -> None:
        self._config = config
        self._worker_port = worker_port
        self._conn: asyncssh.SSHClientConnection | None = None

    # --- lifecycle ---

    async def start(self) -> None:
        await self._connect()

    async def stop(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # --- R/Q call (compatible with WorkerConnector.call) ---

    async def call(self, method: str, params: dict[str, Any] | None = None, *, request_id: str) -> Response:
        try:
            await self._ensure_connected()
            reader, writer = await self._open_direct_tcpip()
            try:
                # Send type byte + request
                writer.write(TYPE_RQ)
                req = Request(id=request_id, method=method, params=params or {})
                writer.write(req.to_bytes())
                await writer.drain()
                resp = await asyncio.wait_for(Response.async_read(reader), timeout=30.0)
                return resp
            finally:
                writer.close()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("SSH call failed: %s", e)
            return Response(
                id=request_id,
                error=ErrorInfo(code=ErrorCode.INTERNAL_ERROR, message=f"SSH error: {e}"),
            )

    # --- Frame channel (for sessions) ---

    async def open_frame_channel(self, token: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | None:
        """Open an SSH direct-tcpip channel as a Frame channel."""
        try:
            await self._ensure_connected()
            reader, writer = await self._open_direct_tcpip()
            writer.write(TYPE_FRAME)
            await writer.drain()
            await write_token(writer, token)
            return reader, writer
        except Exception as e:
            log.error("SSH frame channel failed: %s", e)
            return None

    # --- SSH exec (direct, not through worker) ---

    async def exec(self, command: str) -> dict[str, Any]:
        await self._ensure_connected()
        result = await self._conn.run(command)
        return {
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "exit_code": result.exit_status,
        }

    # --- SFTP ---

    async def sftp_put(self, local_path: str, remote_path: str) -> dict[str, Any]:
        await self._ensure_connected()
        async with self._conn.start_sftp_client() as sftp:
            await sftp.put(local_path, remote_path)
            stat = await sftp.stat(remote_path)
            return {"remote_path": remote_path, "size": stat.size}

    async def sftp_get(self, remote_path: str, local_path: str) -> dict[str, Any]:
        await self._ensure_connected()
        async with self._conn.start_sftp_client() as sftp:
            await sftp.get(remote_path, local_path)
            return {"local_path": local_path, "size": os.path.getsize(local_path)}

    # --- connection management ---

    async def _open_direct_tcpip(self):
        """Open a direct-tcpip channel to the worker's loopback port."""
        return await self._conn.open_connection(
            "127.0.0.1", self._worker_port,
        )

    async def _connect(self) -> None:
        kwargs = self._config.to_connect_kwargs()
        log.info("SSH connecting to %s@%s:%s",
                 kwargs.get("username"), kwargs.get("host"), kwargs.get("port"))
        self._conn = await asyncssh.connect(**kwargs)
        log.info("SSH connected")

    async def _ensure_connected(self) -> None:
        if self._conn is not None and not self._conn.is_closed():
            return
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        log.warning("SSH connection lost, reconnecting...")
        await self._connect()
