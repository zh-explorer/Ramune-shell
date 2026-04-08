"""Output size limiting.

When a tool result exceeds max_length, the full output is saved to disk
and the result is progressively truncated:

1. Long strings  → preview + truncation note with file path
2. Long lists    → first N items + truncation note
3. Fallback      → scalar fields only + file path
"""

from __future__ import annotations

import itertools
import json
import os
import tempfile
from typing import Any

_counter = itertools.count(1)
_output_dir: str | None = None

_MAX_LENGTH = 30000
_STRING_PREVIEW = 8000
_LIST_CAP = 30


def _get_output_dir() -> str:
    global _output_dir
    if _output_dir is None:
        _output_dir = tempfile.mkdtemp(prefix="ramune-shell-output-")
    return _output_dir


def _measure(data: Any) -> int:
    return len(json.dumps(data, ensure_ascii=False, default=str))


def _save_full(data: Any) -> str:
    """Write full result to disk, return file path."""
    output_dir = _get_output_dir()
    output_id = f"out-{next(_counter):06d}"
    path = os.path.join(output_dir, f"{output_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    return path


def limit_output(data: Any, max_length: int = _MAX_LENGTH) -> Any:
    """Truncate data if serialized size exceeds max_length."""
    if not isinstance(data, dict):
        return data
    if _measure(data) <= max_length:
        return data

    path = _save_full(data)

    data = _truncate_strings(data, path)
    if _measure(data) <= max_length:
        return data

    data = _truncate_lists(data, path)
    if _measure(data) <= max_length:
        return data

    return _fallback(data, path)


def _truncate_strings(data: Any, path: str) -> Any:
    if isinstance(data, str):
        if len(data) > _STRING_PREVIEW:
            return (
                data[:_STRING_PREVIEW]
                + f"\n\n[truncated {len(data)} chars, full output: {path}]"
            )
        return data
    if isinstance(data, dict):
        return {k: _truncate_strings(v, path) for k, v in data.items()}
    if isinstance(data, list):
        return [_truncate_strings(item, path) for item in data]
    return data


def _truncate_lists(data: Any, path: str) -> Any:
    if isinstance(data, dict):
        result: dict[str, Any] = {}
        for k, v in data.items():
            if isinstance(v, list) and len(v) > _LIST_CAP:
                result[k] = v[:_LIST_CAP]
                result[f"_{k}_truncated"] = (
                    f"showing {_LIST_CAP} of {len(v)} items, full output: {path}"
                )
            else:
                result[k] = _truncate_lists(v, path)
        return result
    if isinstance(data, list) and len(data) > _LIST_CAP:
        return data[:_LIST_CAP]
    return data


def _fallback(data: Any, path: str) -> dict[str, Any]:
    result: dict[str, Any] = {"_truncated": f"Output too large. Full output: {path}"}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                result[k] = v
    return result
