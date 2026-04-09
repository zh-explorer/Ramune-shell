"""Output size limiting.

When a tool result exceeds max_length, the full output is saved to disk
and the result is progressively truncated:

1. Long strings  → preview + truncation note with file path
2. Long lists    → first N items + truncation note
3. Fallback      → scalar fields only + file path

Files are capped at max_files; oldest are evicted automatically.
Call cleanup() on shutdown to remove all output files.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections import deque
from typing import Any


class OutputStore:
    """Manages output files with automatic eviction."""

    def __init__(
        self,
        max_length: int = 16000,
        string_preview: int = 8000,
        list_cap: int = 30,
        max_files: int = 100,
        output_dir: str = "",
    ) -> None:
        self.max_length = max_length
        self.string_preview = string_preview
        self.list_cap = list_cap
        self.max_files = max_files
        self._output_dir = output_dir or ""
        self._files: deque[str] = deque()
        self._counter = 0

    @property
    def output_dir(self) -> str:
        if not self._output_dir:
            self._output_dir = tempfile.mkdtemp(prefix="ramune-shell-output-")
        return self._output_dir

    def limit(self, data: Any) -> Any:
        """Truncate data if serialized size exceeds max_length."""
        if not isinstance(data, dict):
            return data
        if self._measure(data) <= self.max_length:
            return data

        path = self._save_full(data)

        data = self._truncate_strings(data, path)
        if self._measure(data) <= self.max_length:
            return data

        data = self._truncate_lists(data, path)
        if self._measure(data) <= self.max_length:
            return data

        return self._fallback(data, path)

    def cleanup(self) -> None:
        """Remove all output files. Call on shutdown."""
        if self._output_dir and os.path.isdir(self._output_dir):
            shutil.rmtree(self._output_dir, ignore_errors=True)
        self._files.clear()

    # --- internals ---

    def _save_full(self, data: Any) -> str:
        self._counter += 1
        output_dir = self.output_dir
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"out-{self._counter:06d}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        self._files.append(path)
        self._evict()
        return path

    def _evict(self) -> None:
        while len(self._files) > self.max_files:
            old = self._files.popleft()
            try:
                os.remove(old)
            except FileNotFoundError:
                pass

    @staticmethod
    def _measure(data: Any) -> int:
        return len(json.dumps(data, ensure_ascii=False, default=str))

    def _truncate_strings(self, data: Any, path: str) -> Any:
        if isinstance(data, str):
            if len(data) > self.string_preview:
                return (
                    data[:self.string_preview]
                    + f"\n\n[truncated {len(data)} chars, full output: {path}]"
                )
            return data
        if isinstance(data, dict):
            return {k: self._truncate_strings(v, path) for k, v in data.items()}
        if isinstance(data, list):
            return [self._truncate_strings(item, path) for item in data]
        return data

    def _truncate_lists(self, data: Any, path: str) -> Any:
        if isinstance(data, dict):
            result: dict[str, Any] = {}
            for k, v in data.items():
                if isinstance(v, list) and len(v) > self.list_cap:
                    result[k] = v[:self.list_cap]
                    result[f"_{k}_truncated"] = (
                        f"showing {self.list_cap} of {len(v)} items, full output: {path}"
                    )
                else:
                    result[k] = self._truncate_lists(v, path)
            return result
        if isinstance(data, list) and len(data) > self.list_cap:
            return data[:self.list_cap]
        return data

    @staticmethod
    def _fallback(data: Any, path: str) -> dict[str, Any]:
        result: dict[str, Any] = {"_truncated": f"Output too large. Full output: {path}"}
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, (str, int, float, bool)) or v is None:
                    result[k] = v
        return result
