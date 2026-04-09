"""Tests for MCP task management."""

import asyncio

import pytest

from ramune_shell.mcp.tasks import TaskManager


@pytest.mark.asyncio
async def test_fast_task_returns_directly():
    """Tasks completing within timeout return result directly."""
    mgr = TaskManager(default_timeout=5.0)

    async def fast():
        return {"value": 42}

    result = await mgr.execute(fast())
    assert result == {"value": 42}
    # No tasks left in cache
    assert len(mgr._tasks) == 0


@pytest.mark.asyncio
async def test_slow_task_returns_task_id():
    """Tasks exceeding timeout return task_id for polling."""
    mgr = TaskManager(default_timeout=0.1)

    async def slow():
        await asyncio.sleep(5)
        return {"value": "done"}

    result = await mgr.execute(slow())
    assert "task_id" in result
    assert result["status"] == "running"
    # Task still tracked
    assert len(mgr._tasks) == 1


@pytest.mark.asyncio
async def test_get_result_still_running():
    """get_result for a running task returns running status."""
    mgr = TaskManager(default_timeout=0.1)

    async def slow():
        await asyncio.sleep(5)
        return {"value": "done"}

    result = await mgr.execute(slow())
    task_id = result["task_id"]

    status = mgr.get_result(task_id)
    assert status["status"] == "running"
    assert status["task_id"] == task_id
    # Still tracked (not removed)
    assert task_id in mgr._tasks


@pytest.mark.asyncio
async def test_get_result_completed():
    """get_result for a completed task returns result and removes from cache."""
    mgr = TaskManager(default_timeout=0.05)

    async def medium():
        await asyncio.sleep(0.1)
        return {"value": "done"}

    result = await mgr.execute(medium())
    task_id = result["task_id"]

    # Wait for it to complete
    await asyncio.sleep(0.2)

    status = mgr.get_result(task_id)
    assert status["status"] == "completed"
    assert status["result"] == {"value": "done"}
    # Removed from cache
    assert task_id not in mgr._tasks


@pytest.mark.asyncio
async def test_get_result_not_found():
    mgr = TaskManager()
    result = mgr.get_result("nonexistent")
    assert result["status"] == "not_found"


@pytest.mark.asyncio
async def test_cancel_running_task():
    mgr = TaskManager(default_timeout=0.05)

    async def slow():
        await asyncio.sleep(10)
        return {"value": "done"}

    result = await mgr.execute(slow())
    task_id = result["task_id"]

    cancel_result = mgr.cancel(task_id)
    assert cancel_result["status"] == "cancelled"

    # Give event loop a tick to process cancellation
    await asyncio.sleep(0.01)
    assert task_id not in mgr._tasks or mgr._tasks[task_id].is_done


@pytest.mark.asyncio
async def test_cancel_not_found():
    mgr = TaskManager()
    result = mgr.cancel("nonexistent")
    assert result["status"] == "not_found"
