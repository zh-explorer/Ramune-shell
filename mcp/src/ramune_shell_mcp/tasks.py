"""MCP-layer task management.

Handles timeout-to-async conversion: if a tool call exceeds the MCP
timeout, return a task_id so the agent can poll later.  The underlying
request to the worker continues running regardless.
"""

from __future__ import annotations

import asyncio
import itertools
from enum import Enum
from typing import Any

from ramune_shell_mcp.output import limit_output

_global_counter = itertools.count(1)


def next_request_id() -> str:
    """Global unique ID for all requests (task_id == request_id on wire)."""
    return f"req-{next(_global_counter):06d}"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task:
    """Tracks a single in-flight request to a worker."""

    def __init__(self, task_id: str, async_task: asyncio.Task) -> None:
        self.task_id = task_id
        self.status = TaskStatus.RUNNING
        self._async_task = async_task
        self._result: Any = None
        self._error: str | None = None

    @property
    def is_done(self) -> bool:
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )

    def complete(self, result: Any) -> None:
        self.status = TaskStatus.COMPLETED
        self._result = result

    def fail(self, error: str) -> None:
        self.status = TaskStatus.FAILED
        self._error = error

    def cancel(self) -> None:
        self.status = TaskStatus.CANCELLED

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"task_id": self.task_id, "status": self.status.value}
        if self._result is not None:
            d["result"] = self._result
        if self._error is not None:
            d["error"] = self._error
        return d


class TaskManager:
    """Manages in-flight tasks and their results."""

    def __init__(self, default_timeout: float = 30.0) -> None:
        self._tasks: dict[str, Task] = {}
        self.default_timeout = default_timeout

    async def execute(
        self,
        coro_or_factory,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Execute a coroutine with optional timeout.

        coro_or_factory: either a coroutine, or a callable(task_id) -> coroutine.
        The latter allows passing task_id as request_id to the worker.

        If the coroutine completes within timeout, return its result directly.
        If it times out, return a task_id for later polling.
        """
        if timeout is None:
            timeout = self.default_timeout

        task_id = next_request_id()
        if callable(coro_or_factory) and not asyncio.iscoroutine(coro_or_factory):
            coro = coro_or_factory(task_id)
        else:
            coro = coro_or_factory
        async_task = asyncio.create_task(coro)
        task = Task(task_id, async_task)
        self._tasks[task_id] = task

        # Set up callback to capture result when done
        async_task.add_done_callback(lambda fut: self._on_done(task, fut))

        try:
            result = await asyncio.wait_for(
                asyncio.shield(async_task), timeout=timeout
            )
            # Completed within timeout — return result directly, clean up
            self._tasks.pop(task_id, None)
            return limit_output(result) if isinstance(result, dict) else result
        except asyncio.TimeoutError:
            # Still running — return task_id for polling
            return {
                "task_id": task_id,
                "status": "running",
                "notice": "Request is still running. Use get_result to poll.",
            }

    def _on_done(self, task: Task, fut: asyncio.Future) -> None:
        """Callback when the underlying coroutine finishes."""
        if task.is_done:
            return
        try:
            result = fut.result()
            if isinstance(result, dict) and "error" in result:
                task.fail(result["error"])
            else:
                task.complete(result)
        except asyncio.CancelledError:
            task.cancel()
        except Exception as e:
            task.fail(str(e))

    def get_result(self, task_id: str) -> dict[str, Any]:
        """Get the result of a task. Removes completed tasks from cache."""
        task = self._tasks.get(task_id)
        if task is None:
            return {"task_id": task_id, "status": "not_found"}
        if task.is_done:
            self._tasks.pop(task_id, None)
        result = task.to_dict()
        if task.is_done and "result" in result:
            result["result"] = limit_output(result["result"]) if isinstance(result["result"], dict) else result["result"]
        return result

    def cancel(self, task_id: str) -> dict[str, Any]:
        """Cancel a running task (MCP side). Also cancels the asyncio task."""
        task = self._tasks.get(task_id)
        if task is None:
            return {"task_id": task_id, "status": "not_found"}
        if task.is_done:
            return task.to_dict()
        task._async_task.cancel()
        task.cancel()
        return task.to_dict()

    @property
    def tasks(self) -> dict[str, Task]:
        return self._tasks
