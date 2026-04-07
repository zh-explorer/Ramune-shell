"""Plugin discovery and loading for the worker."""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)


def discover_plugins(
    plugins_dir: Path,
    platform: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Callable]]:
    """Scan plugins directory, filter by platform, load handlers.

    Returns (tools_metadata, handler_map).
    """
    if platform is None:
        platform = _current_platform()

    all_tools: list[dict[str, Any]] = []
    handler_map: dict[str, Callable] = {}

    if not plugins_dir.is_dir():
        log.warning("plugins directory not found: %s", plugins_dir)
        return all_tools, handler_map

    # Add plugins dir to sys.path so we can import sub-packages
    plugins_str = str(plugins_dir)
    if plugins_str not in sys.path:
        sys.path.insert(0, plugins_str)

    for child in sorted(plugins_dir.iterdir()):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        metadata_file = child / "metadata.py"
        if not metadata_file.exists():
            continue

        try:
            tools, handlers = _load_plugin(child, platform)
            all_tools.extend(tools)
            handler_map.update(handlers)
        except Exception:
            log.exception("failed to load plugin: %s", child.name)

    _check_duplicates(all_tools)
    return all_tools, handler_map


def _load_plugin(
    plugin_dir: Path,
    platform: str,
) -> tuple[list[dict[str, Any]], dict[str, Callable]]:
    """Load a single plugin: read metadata, filter by platform, resolve handlers."""
    plugin_name = plugin_dir.name

    # Import metadata
    meta_mod = importlib.import_module(f"{plugin_name}.metadata")
    tools_list: list[dict[str, Any]] = getattr(meta_mod, "TOOLS", [])

    # Import handler module
    handler_mod = importlib.import_module(f"{plugin_name}.handler")

    tools: list[dict[str, Any]] = []
    handlers: dict[str, Callable] = {}

    for tool in tools_list:
        # Filter by platform tag
        tags = tool.get("tags", [])
        platform_tags = [t for t in tags if t.startswith("platform:")]
        if platform_tags and f"platform:{platform}" not in platform_tags:
            log.debug("skipping %s: not for platform %s", tool["name"], platform)
            continue

        # Resolve handler function
        handler_name = tool.get("handler", tool["name"])
        handler_fn = getattr(handler_mod, handler_name, None)
        if handler_fn is None:
            log.warning("handler %s not found in %s", handler_name, plugin_name)
            continue

        tools.append(tool)
        handlers[tool["name"]] = handler_fn

    return tools, handlers


def _check_duplicates(tools: list[dict[str, Any]]) -> None:
    """Raise if tool names collide."""
    seen: dict[str, int] = {}
    for tool in tools:
        name = tool["name"]
        if name in seen:
            raise RuntimeError(f"duplicate tool name: {name}")
        seen[name] = 1


def _current_platform() -> str:
    """Detect current platform."""
    import platform
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    return "linux"
