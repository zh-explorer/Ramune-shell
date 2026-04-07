"""Exec plugin metadata."""

TOOLS = [
    {
        "name": "exec",
        "description": "Execute a shell command on the remote machine.",
        "tags": ["platform:linux", "platform:windows"],
        "params": {
            "command": {
                "type": "string",
                "required": True,
                "description": "Shell command to execute.",
            },
            "cwd": {
                "type": "string",
                "required": False,
                "description": "Working directory.",
            },
        },
    },
]
