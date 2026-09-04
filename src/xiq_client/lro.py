"""Long-running operation (LRO) state helpers.

XIQ answers an LRO poll with::

    {"done": bool, "metadata": {"status": "RUNNING" | "SUCCEEDED" | ...},
     "response": {...}, "error": {...}}

:func:`lro_state` turns that into an :class:`LROState` so scripts never
have to re-derive "is it finished / did it fail" themselves.
"""
from __future__ import annotations

from typing import Any, NamedTuple

LRO_RUNNING_STATUSES = frozenset({"RUNNING", "PENDING", "QUEUED", "IN_PROGRESS"})
LRO_FAILED_STATUSES = frozenset({"FAILED", "FAILURE", "ERROR", "CANCELLED", "CANCELED"})


class LROState(NamedTuple):
    """Decoded state of a long-running operation poll."""

    done: bool
    status: str
    response: Any
    error: Any
    body: Any

    @property
    def failed(self) -> bool:
        return bool(self.error) or self.status in LRO_FAILED_STATUSES

    @property
    def succeeded(self) -> bool:
        return self.done and not self.failed

    @property
    def running(self) -> bool:
        return not self.done


def lro_state(body: Any) -> LROState:
    """Decode an LRO poll body. Non-dict bodies count as finished."""
    if not isinstance(body, dict):
        return LROState(True, "", body, None, body)
    metadata = body.get("metadata") or {}
    status = str(metadata.get("status") or "").upper()
    error = body.get("error")
    done = body.get("done") is True or (bool(status) and status not in LRO_RUNNING_STATUSES)
    if error:
        done = True
    return LROState(done, status, body.get("response"), error, body)
