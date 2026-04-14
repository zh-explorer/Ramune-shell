"""Request dispatch: unified handler registry + session loop."""

from __future__ import annotations

import inspect
import logging
import typing
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from ramune_shell.transport import Request, ServerSession
from ramune_shell.transport.messages import ErrorCode
from ramune_shell.transport.rpc import get_rpc

# --- session state (per-task contextvar) ---

session_state: ContextVar[dict] = ContextVar("session_state")


def get_state() -> dict:
    """Get the current session's state dict. Call from any handler."""
    return session_state.get()

log = logging.getLogger(__name__)


# --- handler registry ---

class _Mode(Enum):
    TYPED = "typed"
    FIELDS = "fields"


@dataclass
class _HandlerEntry:
    handler: Callable
    request_model: type[BaseModel]
    result_model: type[BaseModel]
    mode: _Mode


_HANDLERS: dict[str, _HandlerEntry] = {}


def register_feature(method_name: str, handler: Callable) -> None:
    if method_name in _HANDLERS:
        return
    rpc = get_rpc(method_name)
    sig = inspect.signature(handler)
    hints = typing.get_type_hints(handler)
    params = list(sig.parameters.values())

    mode = _Mode.FIELDS
    if len(params) == 1 and hints.get(params[0].name) is rpc.RequestModel:
        mode = _Mode.TYPED

    if hints.get("return") is not rpc.ResultModel:
        raise TypeError(
            f"'{method_name}': handler return annotation must be "
            f"{rpc.ResultModel.__name__}, got {hints.get('return')!r}",
        )

    _HANDLERS[method_name] = _HandlerEntry(
        handler=handler,
        request_model=rpc.RequestModel,
        result_model=rpc.ResultModel,
        mode=mode,
    )
    log.info("handler '%s' registered (mode=%s)", method_name, mode.value)


def registered_feature_names() -> list[str]:
    return sorted(_HANDLERS.keys())


# --- session dispatch loop ---

async def handle_session(session: ServerSession) -> None:
    """Main dispatch loop for one session. Called as a task per session."""
    state: dict = {}
    token = session_state.set(state)
    try:
        while True:
            req = await session.get_request()
            if req is None:
                break
            try:
                result = await _dispatch(req)
                await session.send_response(req, result)
            except _DispatchError as e:
                await session.send_error(req, e.code, e.message)
            except Exception as e:
                log.exception("dispatch error for %s", req.method)
                await session.send_error(req, ErrorCode.INTERNAL_ERROR, str(e))
    finally:
        session_state.reset(token)
        state.clear()


async def _dispatch(req: Request) -> dict[str, Any]:
    """Route a request to its handler, return result dict."""
    entry = _HANDLERS.get(req.method)
    if entry is None:
        raise _DispatchError(ErrorCode.METHOD_NOT_FOUND, f"method '{req.method}' not available")

    try:
        req_obj = entry.request_model.model_validate(req.params)
    except ValidationError as e:
        raise _DispatchError(ErrorCode.INVALID_PARAMS, f"invalid params: {e}")

    if entry.mode is _Mode.TYPED:
        result = await entry.handler(req_obj)
    else:
        result = await entry.handler(**req_obj.model_dump())

    if not isinstance(result, entry.result_model):
        raise _DispatchError(
            ErrorCode.INTERNAL_ERROR,
            f"'{req.method}' returned {type(result).__name__}, expected {entry.result_model.__name__}",
        )

    return result.model_dump()


class _DispatchError(Exception):
    def __init__(self, code: ErrorCode, message: str):
        self.code = code
        self.message = message
        super().__init__(message)
