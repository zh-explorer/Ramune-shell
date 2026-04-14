"""Tests for TaskExecutor: parallel, serial (Lock), cancel."""

import asyncio

import pytest

from ramune_shell.mcp.executor import Task, TaskExecutor, TaskStatus


async def test_task_execute_success():
    async def _work():
        return {"value": 42}

    task = Task("t1", _work)
    await task.execute()
    assert task.status == TaskStatus.COMPLETED
    assert task.result == {"value": 42}


async def test_task_execute_failure():
    async def _work():
        raise ValueError("boom")

    task = Task("t2", _work)
    await task.execute()
    assert task.status == TaskStatus.FAILED
    assert "boom" in task.error


async def test_task_wait_with_timeout():
    async def _slow():
        await asyncio.sleep(10)

    task = Task("t3", _slow)
    asyncio.create_task(task.execute())
    with pytest.raises(asyncio.TimeoutError):
        await task.wait(timeout=0.1)


async def test_task_cancel():
    started = asyncio.Event()

    async def _slow():
        started.set()
        await asyncio.sleep(10)

    task = Task("t4", _slow)
    atask = asyncio.create_task(task.execute())
    task._atask = atask
    await started.wait()
    task.cancel()
    await asyncio.sleep(0.05)
    assert task.status == TaskStatus.CANCELLED


# --- executor ---

async def test_executor_parallel():
    """Tasks without group run in parallel."""
    executor = TaskExecutor()
    order = []

    async def _work(name, delay):
        order.append(f"start:{name}")
        await asyncio.sleep(delay)
        order.append(f"end:{name}")
        return {"name": name}

    t1 = Task("p1", lambda: _work("A", 0.1))
    t2 = Task("p2", lambda: _work("B", 0.05))
    executor.submit(t1, host="h1")
    executor.submit(t2, host="h1")

    await t1.wait(timeout=2.0)
    await t2.wait(timeout=2.0)

    # B finishes before A (parallel)
    assert order.index("end:B") < order.index("end:A")
    assert t1.result == {"name": "A"}
    assert t2.result == {"name": "B"}


async def test_executor_serial_group():
    """Tasks with same (host, group) run serially."""
    executor = TaskExecutor()
    order = []

    async def _work(name):
        order.append(f"start:{name}")
        await asyncio.sleep(0.05)
        order.append(f"end:{name}")
        return {"name": name}

    t1 = Task("s1", lambda: _work("A"))
    t2 = Task("s2", lambda: _work("B"))
    executor.submit(t1, host="h1", group="gui")
    executor.submit(t2, host="h1", group="gui")

    await t1.wait(timeout=2.0)
    await t2.wait(timeout=2.0)

    # A finishes before B starts (serial)
    assert order == ["start:A", "end:A", "start:B", "end:B"]


async def test_executor_different_groups_parallel():
    """Different groups on same host run in parallel."""
    executor = TaskExecutor()
    order = []

    async def _work(name):
        order.append(f"start:{name}")
        await asyncio.sleep(0.05)
        order.append(f"end:{name}")
        return {}

    t1 = Task("g1", lambda: _work("gui"))
    t2 = Task("g2", lambda: _work("net"))
    executor.submit(t1, host="h1", group="gui")
    executor.submit(t2, host="h1", group="net")

    await t1.wait(timeout=2.0)
    await t2.wait(timeout=2.0)

    # Both start before either ends
    assert order[0] == "start:gui"
    assert order[1] == "start:net"


async def test_executor_different_hosts_parallel():
    """Same group on different hosts run in parallel."""
    executor = TaskExecutor()
    order = []

    async def _work(name):
        order.append(f"start:{name}")
        await asyncio.sleep(0.05)
        order.append(f"end:{name}")
        return {}

    t1 = Task("h1", lambda: _work("host-a"))
    t2 = Task("h2", lambda: _work("host-b"))
    executor.submit(t1, host="a", group="gui")
    executor.submit(t2, host="b", group="gui")

    await t1.wait(timeout=2.0)
    await t2.wait(timeout=2.0)

    assert order[0] == "start:host-a"
    assert order[1] == "start:host-b"


async def test_executor_cancel_running():
    executor = TaskExecutor()
    started = asyncio.Event()

    async def _slow():
        started.set()
        await asyncio.sleep(10)

    task = Task("c1", _slow)
    executor.submit(task, host="h1")
    await started.wait()

    assert executor.cancel("c1") is True
    await asyncio.sleep(0.05)
    assert task.status == TaskStatus.CANCELLED


async def test_executor_cancel_pending_in_group():
    """Cancel a task waiting for group lock."""
    executor = TaskExecutor()

    async def _slow():
        await asyncio.sleep(10)
        return {}

    async def _fast():
        return {}

    t1 = Task("block", _slow)
    t2 = Task("wait", _fast)
    executor.submit(t1, host="h1", group="gui")
    executor.submit(t2, host="h1", group="gui")

    await asyncio.sleep(0.05)
    # t2 is waiting for the lock (t1 holds it)
    assert executor.cancel("wait") is True
    assert t2.status == TaskStatus.CANCELLED

    # Clean up t1
    executor.cancel("block")
