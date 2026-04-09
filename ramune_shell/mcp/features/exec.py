"""Exec feature: execute shell commands on remote machine."""

from __future__ import annotations

from ramune_shell.mcp.feature import feature, ToolContext

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
async def exec(ctx: ToolContext, command: str, cwd: str | None = None) -> dict:
    resp = await ctx.call_plugin("exec", {"command": command, "cwd": cwd})
    if resp.error:
        return {"error": resp.error.message}
    return resp.result
