"""Task executor: concurrent task scheduling with optional serialization.

The executor knows nothing about hosts, sessions, or features.
It receives pre-packaged Tasks and schedules them:
- No concurrency_group → parallel (asyncio.create_task)
- With concurrency_group → serial per (host, group) via asyncio.Lock
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Any, Callable

log = logging.getLogger(__name__)


# ============================================================
# Task
# ============================================================

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task:
    """A self-contained executable unit.

    Callers package everything into `coro_factory` — the executor just
    calls it and tracks the result.
    """

    def __init__(self, task_id: str, coro_factory: Callable[[], Any]) -> None:
        self.task_id = task_id
        self.status = TaskStatus.PENDING
        self._coro_factory = coro_factory
        self._result: Any = None
        self._error: str | None = None
        self._done = asyncio.Event()
        self._atask: asyncio.Task | None = None  # cancel handle

    @property
    def is_done(self) -> bool:
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )

    async def execute(self) -> None:
        """Run the packaged coroutine. Called by the executor."""
        self.status = TaskStatus.RUNNING
        try:
            self._result = await self._coro_factory()
            self.status = TaskStatus.COMPLETED
        except asyncio.CancelledError:
            self.status = TaskStatus.CANCELLED
        except Exception as e:
            self._error = str(e)
            self.status = TaskStatus.FAILED
        finally:
            self._done.set()

    async def wait(self, timeout: float | None = None) -> None:
        """Wait for task completion. Raises asyncio.TimeoutError on timeout."""
        if timeout is not None:
            await asyncio.wait_for(self._done.wait(), timeout=timeout)
        else:
            await self._done.wait()

    def cancel(self) -> None:
        if not self.is_done:
            if self._atask and not self._atask.done():
                self._atask.cancel()
            self.status = TaskStatus.CANCELLED
            self._done.set()

    @property
    def result(self) -> Any:
        return self._result

    @property
    def error(self) -> str | None:
        return self._error

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"task_id": self.task_id, "status": self.status.value}
        if self._result is not None:
            d["result"] = self._result
        if self._error is not None:
            d["error"] = self._error
        return d


# ============================================================
# Executor
# ============================================================

class TaskExecutor:
    """Concurrent task scheduler.

    - No group → parallel (each task gets its own asyncio.Task)
    - With group → serial per (host, group) via asyncio.Lock

    The executor doesn't know what tasks do internally.
    """

    def __init__(self) -> None:
        self._active: dict[str, Task] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    def submit(self, task: Task, host: str, group: str | None = None) -> None:
        """Schedule a task for execution."""
        self._active[task.task_id] = task
        atask = asyncio.create_task(self._run(task, host, group))
        task._atask = atask

    def cancel(self, task_id: str) -> bool:
        """Cancel an active task. Returns True if found."""
        task = self._active.get(task_id)
        if task is None:
            return False
        task.cancel()
        self._active.pop(task_id, None)
        return True

    def get_active(self, task_id: str) -> Task | None:
        return self._active.get(task_id)

    # --- internal ---

    async def _run(self, task: Task, host: str, group: str | None) -> None:
        """Execute a task, respecting concurrency group."""
        if task.is_done:
            self._active.pop(task.task_id, None)
            return

        try:
            if group:
                lock = self._locks.setdefault((host, group), asyncio.Lock())
                async with lock:
                    await task.execute()
            else:
                await task.execute()
        except asyncio.CancelledError:
            if not task.is_done:
                task.cancel()
        finally:
            self._active.pop(task.task_id, None)
