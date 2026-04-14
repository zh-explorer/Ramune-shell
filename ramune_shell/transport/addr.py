"""Operation and session identifiers.

SessionId — frozen session identity.
OpId      — frozen globally unique operation identifier (session + seq).

Both are pydantic BaseModel frozen, natively nestable in other models.
Allocator (counter) lives in the session runtime instance (ToolContext),
not here.
"""

from __future__ import annotations

import itertools
from pydantic import BaseModel


class SessionId(BaseModel, frozen=True):
    id: str

    def __str__(self) -> str:
        return self.id

    def __repr__(self) -> str:
        return f"SessionId({self.id!r})"


class OpId(BaseModel, frozen=True):
    session: str
    seq: str

    def get_session(self) -> SessionId:
        return SessionId(id=self.session)

    def __str__(self) -> str:
        return f"{self.session}/{self.seq}"

    def __repr__(self) -> str:
        return f"OpId({self.session!r}, {self.seq!r})"


# --- global session allocator ---

_session_counter = itertools.count(1)


def new_session() -> SessionId:
    return SessionId(id=f"sess-{next(_session_counter):06d}")


