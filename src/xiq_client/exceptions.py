"""Typed exceptions raised by the client."""
from __future__ import annotations

from typing import Any


class XIQError(Exception):
    """Base class for all xiq-client errors."""


class CredentialsError(XIQError):
    """No usable credentials were supplied or found in the environment."""


class APIError(XIQError):
    """The API returned an error response, or retries were exhausted.

    ``status_code`` is the HTTP status (e.g. 404, 429), or ``None`` when the
    request never got a response (connection errors / timeouts after retries).
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


class AuthenticationError(APIError):
    """Login failed or the token was rejected (HTTP 401/403)."""


class LROTimeoutError(APIError):
    """``wait_lro`` exceeded its timeout before the operation finished."""
