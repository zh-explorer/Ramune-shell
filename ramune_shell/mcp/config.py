"""MCP server configuration."""

from __future__ import annotations

import os

from pydantic import BaseModel


class McpConfig(BaseModel):
    port: int = 9900
    default_timeout: float = 30.0
    output_max_length: int = 16000
    output_string_preview: int = 8000
    output_list_cap: int = 30
    output_max_files: int = 100
    output_dir: str = ""

    @property
    def resolved_output_dir(self) -> str:
        if self.output_dir:
            return os.path.expanduser(self.output_dir)
        return ""  # will use tempdir
