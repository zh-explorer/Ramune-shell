"""Worker-side built-in handlers.

ping / close_session / open_frame_channel are handled by transport layer.
Only business-level builtins remain here: list_features, shutdown.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

from ramune_shell.transport.rpc import register_rpc
from ramune_shell.worker.dispatch import register_feature, registered_feature_names


# --- list_features ---

class ListFeaturesRequest(BaseModel):
    pass

class ListFeaturesResult(BaseModel):
    features: list[str]

register_rpc("list_features", ListFeaturesRequest, ListFeaturesResult)


async def handle_list_features(req: ListFeaturesRequest) -> ListFeaturesResult:
    return ListFeaturesResult(features=registered_feature_names())


# --- shutdown ---

class ShutdownRequest(BaseModel):
    pass

class ShutdownResult(BaseModel):
    pass

register_rpc("shutdown", ShutdownRequest, ShutdownResult)


async def handle_shutdown(req: ShutdownRequest) -> ShutdownResult:
    loop = asyncio.get_running_loop()
    loop.call_soon(loop.stop)
    return ShutdownResult()


# --- registration ---

def register_builtins() -> None:
    register_feature("list_features", handle_list_features)
    register_feature("shutdown", handle_shutdown)
