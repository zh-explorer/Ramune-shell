"""End-to-end tests: MCP feature → transport → worker dispatch."""

import asyncio

import pytest

from ramune_shell.transport import (
    ClientTransport, ServerTransport, TcpConnector, TcpListener,
)
from ramune_shell.worker.dispatch import handle_session, register_feature
from ramune_shell.worker.handlers import register_builtins
from ramune_shell.features.exec import register_worker as register_exec


# --- fixture: full stack ---

_registered = False


def _ensure_registered():
    global _registered
    if not _registered:
        register_builtins()
        register_exec()
        _registered = True


@pytest.fixture
async def stack():
    """Yields (client_transport, server_transport) with worker dispatch running."""
    _ensure_registered()
    listener = TcpListener("127.0.0.1", 0)
    st = ServerTransport(listener)
    await st.start()
    ct = ClientTransport(TcpConnector("127.0.0.1", st.port))

    # Start worker dispatch loop
    async def _worker():
        try:
            while True:
                session = await st.accept_session()
                asyncio.create_task(handle_session(session))
        except asyncio.CancelledError:
            pass

    worker_task = asyncio.create_task(_worker())
    yield ct, st
    worker_task.cancel()
    await ct.close()   # close pool first → TCP connections close
    await st.close()   # then close server


# --- tests ---

async def test_ping(stack):
    ct, st = stack
    session = await ct.open_session()
    assert await session.ping() is True
    await session.close()


async def test_exec_echo(stack):
    ct, st = stack
    session = await ct.open_session()
    resp = await session.request("exec", {"command": "echo hello"})
    assert resp.error is None
    assert resp.result["stdout"].strip() == "hello"
    assert resp.result["exit_code"] == 0
    await session.close()


async def test_exec_stderr(stack):
    ct, st = stack
    session = await ct.open_session()
    resp = await session.request("exec", {"command": "echo err >&2"})
    assert resp.error is None
    assert resp.result["stderr"].strip() == "err"
    await session.close()


async def test_exec_exit_code(stack):
    ct, st = stack
    session = await ct.open_session()
    resp = await session.request("exec", {"command": "exit 42"})
    assert resp.error is None
    assert resp.result["exit_code"] == 42
    await session.close()


async def test_exec_cwd(stack):
    ct, st = stack
    session = await ct.open_session()
    resp = await session.request("exec", {"command": "pwd", "cwd": "/tmp"})
    assert resp.error is None
    assert resp.result["stdout"].strip() == "/tmp"
    await session.close()


async def test_list_features(stack):
    ct, st = stack
    session = await ct.open_session()
    resp = await session.request("list_features", {})
    assert resp.error is None
    assert "exec" in resp.result["features"]
    await session.close()


async def test_unknown_method(stack):
    ct, st = stack
    session = await ct.open_session()
    resp = await session.request("nonexistent", {})
    assert resp.error is not None
    await session.close()


async def test_concurrent_exec(stack):
    ct, st = stack

    async def _run(cmd):
        session = await ct.open_session()
        resp = await session.request("exec", {"command": cmd})
        await session.close()
        return resp.result

    results = await asyncio.gather(
        _run("echo a"), _run("echo b"), _run("echo c"),
    )
    outputs = sorted(r["stdout"].strip() for r in results)
    assert outputs == ["a", "b", "c"]
