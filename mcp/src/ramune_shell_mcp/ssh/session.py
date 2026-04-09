"""SSH session with paramiko.

Each operation runs in a thread via _Op.run().
Connection/reconnection is protected by a lock.
Keepalive runs in a background timer thread.
Operations are cancellable by closing the underlying SSH channel.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, Callable

import paramiko

from ramune_shell_protocol import Request, Response
from ramune_shell_protocol.codec import HEADER

log = logging.getLogger(__name__)


@dataclass
class SshConfig:
    """SSH connection configuration."""

    host: str = ""
    port: int = 22
    user: str = ""
    key_filename: str | None = None
    password: str | None = None
    alias: str | None = None

    def resolve(self) -> dict[str, Any]:
        """Resolve to paramiko connect kwargs."""
        if self.alias:
            return self._resolve_alias()
        result: dict[str, Any] = {
            "hostname": self.host,
            "port": self.port,
            "username": self.user or os.getenv("USER", "root"),
        }
        if self.key_filename:
            result["key_filename"] = self.key_filename
        if self.password:
            result["password"] = self.password
        return result

    def _resolve_alias(self) -> dict[str, Any]:
        ssh_config = paramiko.SSHConfig()
        config_path = os.path.expanduser("~/.ssh/config")
        if os.path.exists(config_path):
            with open(config_path) as f:
                ssh_config.parse(f)
        lookup = ssh_config.lookup(self.alias)

        result: dict[str, Any] = {
            "hostname": lookup.get("hostname", self.host or self.alias),
            "port": int(lookup.get("port", self.port)),
            "username": lookup.get("user", self.user or os.getenv("USER", "root")),
        }
        identity = lookup.get("identityfile")
        if identity:
            result["key_filename"] = [os.path.expanduser(k) for k in identity]
        elif self.key_filename:
            result["key_filename"] = self.key_filename
        if self.password:
            result["password"] = self.password
        return result


class _Op:
    """Cancellable threaded operation.

    Wraps a sync function in asyncio.to_thread with cancellation support.
    The sync function receives this _Op as first argument and should call
    set_resource() to register the closeable resource (channel/sftp).
    On cancel, the resource is closed, causing blocking IO to error out.
    """

    def __init__(self) -> None:
        self._resource = None
        self._cancelled = False

    def set_resource(self, resource) -> None:
        self._resource = resource
        if self._cancelled:
            resource.close()

    def cancel(self) -> None:
        self._cancelled = True
        if self._resource:
            try:
                self._resource.close()
            except Exception:
                pass

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    async def run(self, fn: Callable, *args) -> Any:
        """Run fn(op, *args) in a thread. Cancel-safe."""
        try:
            return await asyncio.to_thread(fn, self, *args)
        except asyncio.CancelledError:
            self.cancel()
            raise


class SshSession:
    """SSH session backed by paramiko. Thread-safe for concurrent operations."""

    def __init__(self, config: SshConfig, worker_port: int = 9800) -> None:
        self._config = config
        self._worker_port = worker_port
        self._client: paramiko.SSHClient | None = None
        self._lock = threading.Lock()
        self._keepalive_timer: threading.Timer | None = None
        self._stopped = False

    # --- lifecycle ---

    def start(self) -> None:
        self._connect()
        self._schedule_keepalive()

    def stop(self) -> None:
        self._stopped = True
        if self._keepalive_timer:
            self._keepalive_timer.cancel()
        self._disconnect()

    # --- async interface ---

    async def call(self, method: str, params: dict[str, Any] | None = None, *, request_id: str) -> Response:
        try:
            return await _Op().run(self._do_call, method, params or {}, request_id)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("SSH call failed: %s", e)
            from ramune_shell_protocol import ErrorCode
            from ramune_shell_protocol.messages import ErrorInfo
            return Response(
                id=request_id,
                error=ErrorInfo(code=ErrorCode.INTERNAL_ERROR, message=f"SSH error: {e}"),
            )

    async def exec(self, command: str) -> dict[str, Any]:
        return await _Op().run(self._do_exec, command)

    async def sftp_put(self, local_path: str, remote_path: str) -> dict[str, Any]:
        return await _Op().run(self._do_sftp_put, local_path, remote_path)

    async def sftp_get(self, remote_path: str, local_path: str) -> dict[str, Any]:
        return await _Op().run(self._do_sftp_get, remote_path, local_path)

    # --- sync operations (run in threads via _Op) ---

    def _do_call(self, op: _Op, method: str, params: dict[str, Any], request_id: str) -> Response:
        self._ensure_connected()
        channel = self._client.get_transport().open_channel(
            "direct-tcpip",
            ("127.0.0.1", self._worker_port),
            ("127.0.0.1", 0),
        )
        op.set_resource(channel)
        try:
            req = Request(id=request_id, method=method, params=params)
            channel.sendall(req.to_bytes())

            header = self._recv_exact(channel, HEADER.size)
            (length,) = HEADER.unpack(header)
            payload = self._recv_exact(channel, length)
            return Response.from_bytes(payload)
        except (OSError, EOFError, ConnectionError):
            if op.cancelled:
                raise asyncio.CancelledError
            raise
        finally:
            channel.close()

    def _do_exec(self, op: _Op, command: str) -> dict[str, Any]:
        self._ensure_connected()
        _, stdout, stderr = self._client.exec_command(command)
        op.set_resource(stdout.channel)
        try:
            exit_code = stdout.channel.recv_exit_status()
            return {
                "stdout": stdout.read().decode(errors="replace"),
                "stderr": stderr.read().decode(errors="replace"),
                "exit_code": exit_code,
            }
        except (OSError, EOFError, ConnectionError):
            if op.cancelled:
                raise asyncio.CancelledError
            raise

    def _do_sftp_put(self, op: _Op, local_path: str, remote_path: str) -> dict[str, Any]:
        self._ensure_connected()
        sftp = self._client.open_sftp()
        op.set_resource(sftp)
        try:
            sftp.put(local_path, remote_path)
            stat = sftp.stat(remote_path)
            return {"remote_path": remote_path, "size": stat.st_size}
        except (OSError, EOFError, ConnectionError):
            if op.cancelled:
                raise asyncio.CancelledError
            raise
        finally:
            sftp.close()

    def _do_sftp_get(self, op: _Op, remote_path: str, local_path: str) -> dict[str, Any]:
        self._ensure_connected()
        sftp = self._client.open_sftp()
        op.set_resource(sftp)
        try:
            sftp.get(remote_path, local_path)
            return {"local_path": local_path, "size": os.path.getsize(local_path)}
        except (OSError, EOFError, ConnectionError):
            if op.cancelled:
                raise asyncio.CancelledError
            raise
        finally:
            sftp.close()

    @staticmethod
    def _recv_exact(channel, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = channel.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("SSH channel closed unexpectedly")
            buf.extend(chunk)
        return bytes(buf)

    # --- connection management (lock-protected) ---

    def _connect(self) -> None:
        with self._lock:
            resolved = self._config.resolve()
            log.info("SSH connecting to %s@%s:%s",
                     resolved.get("username"), resolved["hostname"], resolved["port"])
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self._client.connect(**resolved)
            log.info("SSH connected")

    def _disconnect(self) -> None:
        with self._lock:
            if self._client:
                self._client.close()
                self._client = None

    def _ensure_connected(self) -> None:
        with self._lock:
            if self._client:
                transport = self._client.get_transport()
                if transport and transport.is_active():
                    return
            log.warning("SSH connection lost, reconnecting...")
        self._connect()

    # --- keepalive ---

    def _schedule_keepalive(self) -> None:
        if self._stopped:
            return
        self._keepalive_timer = threading.Timer(30.0, self._keepalive)
        self._keepalive_timer.daemon = True
        self._keepalive_timer.start()

    def _keepalive(self) -> None:
        if self._stopped:
            return
        try:
            with self._lock:
                if self._client:
                    transport = self._client.get_transport()
                    if transport and transport.is_active():
                        transport.send_ignore()
        except Exception:
            log.debug("keepalive failed", exc_info=True)
        self._schedule_keepalive()
