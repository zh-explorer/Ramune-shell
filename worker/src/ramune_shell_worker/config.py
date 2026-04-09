"""Worker daemon configuration."""

from __future__ import annotations

from pydantic import BaseModel


class WorkerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 9800
    plugins_dir: str = ""
