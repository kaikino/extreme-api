"""HTTP core shared by :class:`xiq_client.XIQ`.

Timeouts, retries with backoff, rate-limit handling, pagination, and
long-running-operation polling. Nothing in here knows about XIQ resources.
"""
from __future__ import annotations

import logging
import random
import sys
import time
from collections.abc import Iterator
from typing import Any, Callable

import requests

from .exceptions import (
    APIError,
    AuthenticationError,
    DuplicateNameError,
    LROFailedError,
    LROTimeoutError,
    NotFoundError,
    error_message,
    looks_like_duplicate,
)
from .lro import LROState, lro_state

logger = logging.getLogger("xiq_client")

DEFAULT_TIMEOUT = (10.0, 60.0)  # (connect, read) seconds
DEFAULT_MAX_RETRIES = 5
DEFAULT_PAGE_SIZE = 100
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_BACKOFF_SECONDS = 60.0  # cap for Retry-After and backoff sleeps
DEFAULT_LRO_TIMEOUT = 300.0
DEFAULT_LRO_INTERVAL = 2.0

ProgressCallback = Callable[[str], None]
PollCallback = Callable[[LROState, float], None]
PageCallback = Callable[[int, int, int], None]


def print_progress(message: str) -> None:
    """Default progress reporter: one line on stderr."""
    print(message, file=sys.stderr, flush=True)


def _query(params: dict | None) -> dict | None:
    """Render query parameters the way the API expects them.

    ``requests`` would send a Python ``bool`` as ``True`` / ``False``;
    XIQ wants ``true`` / ``false``. Lists stay lists so they keep being
    sent as repeated parameters.
    """
    if not params:
        return None
    rendered: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, bool):
            rendered[key] = "true" if value else "false"
        elif isinstance(value, (list, tuple)):
            rendered[key] = [
                ("true" if v else "false") if isinstance(v, bool) else v for v in value
            ]
        else:
            rendered[key] = value
    return rendered


class BaseClient:
    """Retrying HTTP client with XIQ-style pagination and LRO polling."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        session: requests.Session | None = None,
        progress: bool | ProgressCallback = False,
        retry_unsafe: bool = False,
        user_agent: str = "xiq-client",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(1, int(max_retries))
        self.retry_unsafe = retry_unsafe
        self.progress: bool | ProgressCallback = progress
        self._user_agent = user_agent
        self._token: str | None = None
        self._sleep: Callable[[float], None] = time.sleep
        self.session = self._new_session() if session is None else session
        self.session.headers.setdefault("Accept", "application/json")

    # ------------------------------------------------------------------
    # session / token
    # ------------------------------------------------------------------
    def _new_session(self) -> requests.Session:
        session = requests.Session()
        session.headers["User-Agent"] = self._user_agent
        return session

    def _set_token(self, token: str) -> None:
        self._token = token
        self.session.headers["Authorization"] = "Bearer " + token

    @property
    def token(self) -> str | None:
        """The bearer token currently in use (after login or account switch)."""
        return self._token

    def close(self) -> None:
        """Close the underlying HTTP session. The token is not revoked."""
        self.session.close()

    def __enter__(self):  # noqa: ANN204 - returns Self, which py39 cannot spell
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # progress reporting
    # ------------------------------------------------------------------
    def _report(self, message: str) -> None:
        callback = self.progress
        if callback is True:
            print_progress(message)
        elif callable(callback):
            callback(message)

    # ------------------------------------------------------------------
    # request / retry / finish
    # ------------------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,
        data: Any = None,
        files: dict | None = None,
        raw: bool = False,
        return_location: bool = False,
        expect_json: bool = True,
    ) -> Any:
        """Perform a request with retries; return the decoded response.

        ``data`` sends a raw (non-JSON) body, ``files`` a multipart upload,
        ``raw=True`` returns bytes, ``return_location=True`` returns the
        Location header (long-running operations).

        Retry policy: connection failures and 429/502/503/504 are retried
        for every method. Read timeouts and HTTP 500 are retried only for
        GET (the request may already have been applied) unless the client
        was created with ``retry_unsafe=True``.
        """
        if path.startswith(("http://", "https://")):
            url = path
        else:
            url = self.base_url + "/" + path.lstrip("/")
        safe = method.upper() == "GET" or self.retry_unsafe
        last_exc: Exception | None = None
        response: requests.Response | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.request(
                    method, url, params=_query(params), json=json, data=data,
                    files=files, timeout=self.timeout,
                )
            except requests.ConnectionError as exc:  # includes ConnectTimeout
                last_exc = exc
                retryable = True
            except requests.Timeout as exc:  # ReadTimeout
                last_exc = exc
                retryable = safe
            else:
                status = response.status_code
                if (
                    status in RETRY_STATUSES
                    and attempt < self.max_retries
                    and (safe or status != 500)
                ):
                    logger.warning(
                        "%s %s -> HTTP %d, attempt %d/%d",
                        method, url, status, attempt, self.max_retries,
                    )
                    self._backoff(attempt, response.headers.get("Retry-After"))
                    continue
                return self._finish(method, url, response, expect_json, raw, return_location)

            if not retryable or attempt >= self.max_retries:
                break
            logger.warning(
                "%s %s failed (%s), attempt %d/%d",
                method, url, type(last_exc).__name__, attempt, self.max_retries,
            )
            self._backoff(attempt, None)

        raise APIError(
            f"{method} {url} failed after {attempt} attempt(s): {last_exc}",
            method=method,
            url=url,
        ) from last_exc

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        delay: float
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = 2.0 ** attempt
        else:
            delay = 2.0 ** attempt * (0.5 + random.random() / 2)
        self._sleep(min(delay, MAX_BACKOFF_SECONDS))

    def _finish(
        self,
        method: str,
        url: str,
        response: requests.Response,
        expect_json: bool,
        raw: bool = False,
        return_location: bool = False,
    ) -> Any:
        status = response.status_code
        if 200 <= status < 300:
            if return_location:
                return response.headers.get("Location")
            if raw:
                return response.content
            if not expect_json or not response.content:
                return response.text or None
            try:
                return response.json()
            except ValueError:
                return response.text or None

        body: Any
        try:
            body = response.json()
        except ValueError:
            body = response.text
        detail = error_message(body) or str(body)[:300]
        message = f"{method} {url} -> HTTP {status}: {detail}"
        kwargs = {"status_code": status, "method": method, "url": url, "body": body}

        if status in (401, 403):
            raise AuthenticationError(message, **kwargs)
        if status == 404:
            raise NotFoundError(message, **kwargs)
        if status in (400, 409, 422) and looks_like_duplicate(body):
            raise DuplicateNameError(message, **kwargs)
        raise APIError(message, **kwargs)

    # ------------------------------------------------------------------
    # verbs
    # ------------------------------------------------------------------
    def get(self, path: str, **params: Any) -> Any:
        """GET ``path``. Query string from keyword arguments."""
        return self._request("GET", path, params=params or None)

    def post(self, path: str, json: Any = None, **params: Any) -> Any:
        """POST ``path`` with an optional JSON body. Query string from kwargs."""
        return self._request("POST", path, json=json, params=params or None)

    def put(self, path: str, json: Any = None, **params: Any) -> Any:
        """PUT ``path`` with an optional JSON body. Query string from kwargs."""
        return self._request("PUT", path, json=json, params=params or None)

    def delete(self, path: str, json: Any = None, **params: Any) -> Any:
        """DELETE ``path``. Optional JSON body; query string from kwargs."""
        return self._request("DELETE", path, json=json, params=params or None)

    # ------------------------------------------------------------------
    # long-running operations
    # ------------------------------------------------------------------
    def post_lro(
        self,
        path: str,
        json: Any = None,
        *,
        params: dict | None = None,
        files: dict | None = None,
    ) -> str | None:
        """POST a long-running operation; returns the Location URL to poll."""
        return self._request(
            "POST", path, json=json, params=params, files=files, return_location=True
        )

    def check_lro(self, url: str) -> Any:
        """GET a long-running operation's Location URL once (raw body)."""
        return self._request("GET", url)

    def lro(self, url: str) -> LROState:
        """GET a long-running operation's Location URL once, decoded."""
        return lro_state(self.check_lro(url))

    def wait_lro(
        self,
        url: str,
        *,
        timeout: float = DEFAULT_LRO_TIMEOUT,
        interval: float = DEFAULT_LRO_INTERVAL,
        initial_delay: float = 0.0,
        on_poll: PollCallback | None = None,
        raise_on_failure: bool = True,
    ) -> LROState:
        """Poll an LRO URL until it finishes or ``timeout`` seconds elapse.

        ``on_poll(state, elapsed)`` is called after every poll so scripts can
        print a spinner or status line. Raises :class:`LROTimeoutError` on
        timeout and :class:`LROFailedError` if the operation failed (unless
        ``raise_on_failure=False``, in which case the failed state is
        returned).
        """
        start = time.monotonic()
        deadline = start + timeout
        if initial_delay > 0:
            self._sleep(initial_delay)
        state: LROState | None = None
        while True:
            try:
                state = self.lro(url)
            except APIError as exc:
                if exc.status_code is None or exc.status_code >= 500:
                    # transient; keep polling until the deadline
                    state = LROState(False, f"HTTP ERROR {exc.status_code or ''}".strip(),
                                     None, None, exc.body)
                else:
                    raise
            elapsed = time.monotonic() - start
            self._report(f"LRO {state.status or 'RUNNING'} ({elapsed:.0f}s)")
            if on_poll is not None:
                on_poll(state, elapsed)
            if state.done:
                if state.failed and raise_on_failure:
                    raise LROFailedError(
                        f"LRO {url} failed: {error_message(state.error) or state.status}",
                        method="GET",
                        url=url,
                        body=state.body,
                    )
                return state
            if time.monotonic() >= deadline:
                raise LROTimeoutError(
                    f"LRO {url} did not finish within {timeout}s",
                    method="GET",
                    url=url,
                    body=state.body,
                )
            self._sleep(interval)

    # ------------------------------------------------------------------
    # pagination
    # ------------------------------------------------------------------
    def first_page(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        page: int = 1,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> dict:
        """GET one page of a list endpoint; returns the raw page dict.

        XIQ list endpoints respond with
        ``{"page", "count", "total_pages", "total_count", "data": [...]}``.
        Endpoints that answer with a bare list are wrapped into that shape.
        """
        merged = dict(params or {})
        merged["page"] = page
        merged["limit"] = limit
        body = self._request("GET", path, params=merged)
        if isinstance(body, dict):
            return body
        data = list(body or [])
        return {
            "page": page,
            "count": len(data),
            "total_pages": 1,
            "total_count": len(data),
            "data": data,
        }

    def count(self, path: str, **params: Any) -> int:
        """Total number of items a list endpoint would return (one request)."""
        page = self.first_page(path, params, limit=1)
        for key in ("total_count", "count"):
            value = page.get(key)
            if isinstance(value, int):
                return value
        return len(page.get("data") or [])

    def paged(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        on_page: PageCallback | None = None,
    ) -> Iterator[dict]:
        """Iterate every item of a paginated list endpoint.

        ``on_page(page, total_pages, items_on_page)`` is called after each
        page. The client's ``progress`` setting reports pages too.
        """
        page = 1
        while True:
            body = self.first_page(path, params, page=page, limit=limit)
            data = body.get("data") or []
            total_pages = int(body.get("total_pages") or 1)
            self._report(f"{path}: page {page} of {total_pages}")
            if on_page is not None:
                on_page(page, total_pages, len(data))
            yield from data
            if page >= total_pages or not data:
                return
            page += 1

    def _list(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[dict]:
        return list(self.paged(path, params, limit=limit))
