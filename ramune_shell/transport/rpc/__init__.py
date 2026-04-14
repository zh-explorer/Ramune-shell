"""Typed RPC registry.

Each feature registers a (RequestModel, ResultModel) pair here so that
both MCP and worker ends validate/serialize through the same schema.
"""

from __future__ import annotations

from typing import NamedTuple

from pydantic import BaseModel


class FeatureRPC(NamedTuple):
    RequestModel: type[BaseModel]
    ResultModel: type[BaseModel]


FEATURE_RPCS: dict[str, FeatureRPC] = {}


def register_rpc(
    tool_name: str,
    request_model: type[BaseModel],
    result_model: type[BaseModel],
) -> None:
    """Register a feature's RPC types. Both models must be pydantic BaseModels."""
    if tool_name in FEATURE_RPCS:
        raise ValueError(f"rpc already registered: {tool_name}")
    FEATURE_RPCS[tool_name] = FeatureRPC(request_model, result_model)


def get_rpc(tool_name: str) -> FeatureRPC:
    rpc = FEATURE_RPCS.get(tool_name)
    if rpc is None:
        raise KeyError(f"no rpc registered for feature: {tool_name}")
    return rpc


# RPC types are registered by:
# - transport/session.py internal protocol (ping, close_session, open_frame_channel)
# - worker/handlers.py (list_features, shutdown)
# - features/*.py (exec, etc.)
# All registration happens at import time via register_rpc() calls.
