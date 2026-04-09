"""Exec feature: execute shell commands."""

from __future__ import annotations

import asyncio
from typing import Any

from ramune_shell.worker.dispatch import register_module

MODULE = "exec"


async def exec_handler(params: dict[str, Any]) -> dict[str, Any]:
    command = params["command"]
    cwd = params.get("cwd")

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    try:
        stdout, stderr = await proc.communicate()
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise

    return {
        "stdout": stdout.decode(errors="replace"),
        "stderr": stderr.decode(errors="replace"),
        "exit_code": proc.returncode,
    }


def register():
    register_module(MODULE, {"exec": exec_handler})
