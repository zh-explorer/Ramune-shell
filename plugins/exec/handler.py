"""Exec plugin handler."""

from __future__ import annotations

import asyncio
from typing import Any


async def exec(params: dict[str, Any]) -> dict[str, Any]:
    """Execute a shell command and return stdout, stderr, exit_code."""
    command = params["command"]
    cwd = params.get("cwd")

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await proc.communicate()

    return {
        "stdout": stdout.decode(errors="replace"),
        "stderr": stderr.decode(errors="replace"),
        "exit_code": proc.returncode,
    }
