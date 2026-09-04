"""Typed exceptions raised by the client.

Hierarchy::

    XIQError
    ├── CredentialsError        no usable credentials
    └── APIError                the API answered with an error (or never answered)
        ├── AuthenticationError HTTP 401 / 403
        ├── NotFoundError       HTTP 404, or a by-name lookup found nothing
        ├── AmbiguousNameError  a by-name lookup matched more than one object
        ├── DuplicateNameError  the API rejected a create because the name exists
        ├── LROFailedError      a long-running operation finished with an error
        └── LROTimeoutError     a long-running operation did not finish in time
"""
from __future__ import annotations

import re
from typing import Any

_DUPLICATE_RE = re.compile(r"duplicate|already exist|already in use|already used", re.I)


def error_message(body: Any) -> str | None:
    """Best-effort human message from an XIQ error body.

    XIQ answers errors with ``{"error_code": ..., "error_message": ...}``;
    some endpoints use ``message`` or ``detail`` instead.
    """
    if isinstance(body, dict):
        for key in ("error_message", "message", "detail"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        nested = body.get("error")
        if isinstance(nested, (dict, str)):
            return error_message(nested)
        return None
    if isinstance(body, str) and body.strip():
        return body.strip()
    return None


def error_code(body: Any) -> str | None:
    if isinstance(body, dict):
        for key in ("error_code", "error_id", "code"):
            value = body.get(key)
            if value not in (None, ""):
                return str(value)
    return None


def looks_like_duplicate(body: Any) -> bool:
    text = " ".join(filter(None, (error_message(body), error_code(body))))
    return bool(_DUPLICATE_RE.search(text))


class XIQError(Exception):
    """Base class for all xiq-client errors."""


class CredentialsError(XIQError):
    """No usable credentials were supplied or found in the environment."""


class APIError(XIQError):
    """The API returned an error response, or retries were exhausted.

    ``status_code`` is the HTTP status (e.g. 404, 429), or ``None`` when the
    request never got a response (connection errors / timeouts after
    retries) or the error was raised by the client itself.
    ``error_message`` is the API's own message when the body carries one.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        method: str | None = None,
        url: str | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.method = method
        self.url = url
        self.body = body

    @property
    def error_message(self) -> str | None:
        """The ``error_message`` (or similar) field from the response body."""
        return error_message(self.body)

    @property
    def error_code(self) -> str | None:
        """The ``error_code`` field from the response body, if any."""
        return error_code(self.body)


class AuthenticationError(APIError):
    """Login failed or the token was rejected (HTTP 401/403)."""


class NotFoundError(APIError):
    """HTTP 404, or a by-name helper found no matching object."""


class AmbiguousNameError(APIError):
    """A by-name lookup matched more than one object (``status_code`` is None).

    ``matches`` holds the candidate objects so callers can list them.
    """

    def __init__(self, message: str, *, matches: list | None = None) -> None:
        super().__init__(message)
        self.matches = matches or []


class DuplicateNameError(APIError):
    """A create call was rejected because an object with that name exists."""


class LROFailedError(APIError):
    """A long-running operation finished with a failure status."""


class LROTimeoutError(APIError):
    """``wait_lro`` exceeded its timeout before the operation finished."""
