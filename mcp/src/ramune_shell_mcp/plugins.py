"""Plugin discovery and MCP tool registration."""

from __future__ import annotations

import importlib
import inspect
import logging
import sys
from pathlib import Path
from typing import Any, Annotated

from pydantic import Field
from mcp.server.fastmcp import FastMCP

from ramune_shell_mcp.connector import WorkerConnector

log = logging.getLogger(__name__)

_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}


def discover_metadata(plugins_dir: Path) -> list[dict[str, Any]]:
    """Scan plugins directory and collect all tool metadata."""
    all_tools: list[dict[str, Any]] = []

    if not plugins_dir.is_dir():
        log.warning("plugins directory not found: %s", plugins_dir)
        return all_tools

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
            meta_mod = importlib.import_module(f"{child.name}.metadata")
            tools = getattr(meta_mod, "TOOLS", [])
            all_tools.extend(tools)
        except Exception:
            log.exception("failed to load metadata from: %s", child.name)

    return all_tools


def register_plugin_tools(
    mcp_server: FastMCP,
    tools: list[dict[str, Any]],
    get_connector,
) -> None:
    """Register plugin tools as MCP tools from metadata."""
    for meta in tools:
        _register_one(mcp_server, meta, get_connector)


def _register_one(
    mcp_server: FastMCP,
    meta: dict[str, Any],
    get_connector,
) -> None:
    """Register a single plugin tool on the MCP server."""
    tool_name = meta["name"]
    description = meta["description"]
    tags = meta.get("tags", [])

    # Build tag info into description
    if tags:
        description = f"{description} [{', '.join(tags)}]"

    # Build parameter list: required params first, then optional (including host)
    required_params: list[inspect.Parameter] = []
    optional_params: list[inspect.Parameter] = []

    params_def = meta.get("params", {})
    for pname, pdef in params_def.items():
        py_type = _TYPE_MAP.get(pdef.get("type", "string"), str)
        required = pdef.get("required", False)
        pdesc = pdef.get("description", "")

        if required:
            required_params.append(
                inspect.Parameter(
                    pname,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=Annotated[py_type, Field(description=pdesc)],
                )
            )
        else:
            default = pdef.get("default")
            optional_params.append(
                inspect.Parameter(
                    pname,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=Annotated[py_type | None, Field(description=pdesc)],
                    default=default,
                )
            )

    # host is optional, goes after required params
    host_param = inspect.Parameter(
        "host",
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[str, Field(description="Target host identifier")],
        default="default",
    )

    parameters = required_params + [host_param] + optional_params
    sig = inspect.Signature(parameters, return_annotation=dict)

    # Create the tool function
    async def _tool_fn(_tool_name=tool_name, **kwargs):
        host = kwargs.pop("host", "default")
        connector = get_connector(host)
        resp = await connector.call(f"plugin:{_tool_name}", kwargs)
        if resp.error:
            return {"error": resp.error.message}
        return resp.result

    _tool_fn.__name__ = tool_name
    _tool_fn.__qualname__ = tool_name
    _tool_fn.__doc__ = description
    _tool_fn.__signature__ = sig

    mcp_server.tool()(_tool_fn)
