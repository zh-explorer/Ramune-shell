"""Exec feature: execute shell commands on remote machine.

RPC types, MCP-side handler, and worker-side handler — all in one file.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

from ramune_shell.transport import register_rpc
from ramune_shell.mcp import feature, ToolContext
from ramune_shell.worker import register_feature


# --- RPC types (shared between MCP and worker) ---

class ExecRequest(BaseModel):
    command: str
    cwd: str | None = None


class ExecResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int


register_rpc("exec", ExecRequest, ExecResult)


# --- MCP-side handler ---

META = {
    "name": "exec",
    "description": "Execute a shell command on remote machine.",
    "tags": ["module:exec", "platform:linux", "platform:windows"],
    "params": {
        "host": {"type": "string", "required": True},
        "command": {"type": "string", "required": True},
        "cwd": {"type": "string", "required": False},
    },
}


@feature(META)
async def exec_mcp(ctx: ToolContext, command: str, cwd: str | None = None) -> dict:
    result: ExecResult = await ctx.call_feature(
        "exec", ExecRequest(command=command, cwd=cwd),
    )
    return result.model_dump()


# --- Worker-side handler ---

async def exec_worker(command: str, cwd: str | None = None) -> ExecResult:
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

    return ExecResult(
        stdout=stdout.decode(errors="replace"),
        stderr=stderr.decode(errors="replace"),
        exit_code=proc.returncode,
    )


def register_worker():
    register_feature("exec", exec_worker)
