"""ExtremeCloud IQ API client.

The class is named ``XIQ`` to match the ``xiq_api.py`` copies it replaces,
so migrating a script is mostly an import change.
"""
from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Iterator, Sequence
from typing import Any, Callable

import requests

from .exceptions import APIError, AuthenticationError, CredentialsError, XIQError

logger = logging.getLogger("xiq_client")

#: ExtremeCloud IQ API endpoint (old)
XIQ_BASE_URL = "https://api.extremecloudiq.com"
#: Extreme Platform ONE API endpoint
PLATFORM_ONE_BASE_URL = "https://cloudapi.extremecloudiq.com/xiq/v1"

ENV_TOKEN = "XIQ_TOKEN"
ENV_USERNAME = "XIQ_USERNAME"
ENV_PASSWORD = "XIQ_PASSWORD"

DEFAULT_TIMEOUT = (10.0, 60.0)  # (connect, read) seconds
DEFAULT_MAX_RETRIES = 5
DEFAULT_PAGE_SIZE = 100
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_BACKOFF_SECONDS = 60.0  # cap for Retry-After and backoff sleeps


class XIQ:
    """ExtremeCloud IQ API client.

    Examples
    --------
    >>> xiq = XIQ()                          # token from XIQ_TOKEN env var
    >>> xiq = XIQ(token="...")               # explicit token (preferred)
    >>> xiq = XIQ(username="u", password="p")  # legacy login flow
    >>> from xiq_client import PLATFORM_ONE_BASE_URL
    >>> xiq = XIQ(token="...", base_url=PLATFORM_ONE_BASE_URL)  # Platform ONE
    """

    def __init__(
        self,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        *,
        base_url: str = XIQ_BASE_URL,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.session.headers.setdefault("Accept", "application/json")
        self._sleep: Callable[[float], None] = time.sleep

        # Explicit args win over env vars
        # .env file is used when python-dotenv is installed
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        token = token or os.environ.get(ENV_TOKEN) or None
        username = username or os.environ.get(ENV_USERNAME) or None
        password = password or os.environ.get(ENV_PASSWORD) or None
        if token:
            self._set_token(token)
        elif username and password:
            self._login(username, password)
        else:
            raise CredentialsError(
                "No credentials: pass token= or username=/password=, or set "
                f"{ENV_TOKEN} (preferred) or {ENV_USERNAME}/{ENV_PASSWORD}."
            )

    # ------------------------------------------------------------------
    # HTTP core: timeouts, retries, rate-limit handling
    # ------------------------------------------------------------------
    def _set_token(self, token: str) -> None:
        self.session.headers["Authorization"] = "Bearer " + token

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,
        expect_json: bool = True,
    ) -> Any:
        """Perform a request with retries; return parsed JSON (or text)."""
        url = self.base_url + "/" + path.lstrip("/")
        last_exc: Exception | None = None
        response: requests.Response | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.request(
                    method, url, params=params, json=json, timeout=self.timeout
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                logger.warning(
                    "%s %s failed (%s), attempt %d/%d",
                    method, url, type(exc).__name__, attempt, self.max_retries,
                )
                self._backoff(attempt, None)
                continue

            if response.status_code in RETRY_STATUSES and attempt < self.max_retries:
                logger.warning(
                    "%s %s -> HTTP %d, attempt %d/%d",
                    method, url, response.status_code, attempt, self.max_retries,
                )
                self._backoff(attempt, response.headers.get("Retry-After"))
                continue
            return self._finish(method, url, response, expect_json)

        if response is not None:
            # retries exhausted on a retryable status
            return self._finish(method, url, response, expect_json)
        raise APIError(
            f"{method} {url} failed after {self.max_retries} attempts: {last_exc}",
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
        self, method: str, url: str, response: requests.Response, expect_json: bool
    ) -> Any:
        status = response.status_code
        if 200 <= status < 300:
            if not expect_json or not response.content:
                return response.text or None
            return response.json()

        body: Any
        try:
            body = response.json()
        except ValueError:
            body = response.text
        message = f"{method} {url} -> HTTP {status}: {str(body)[:300]}"

        if status in (401, 403):
            raise AuthenticationError(message)
        raise APIError(message, status_code=status, method=method, url=url, body=body)

    # ------------------------------------------------------------------
    # low-level escape hatches
    # ------------------------------------------------------------------
    def get(self, path: str, **params: Any) -> Any:
        return self._request("GET", path, params=params or None)

    def post(self, path: str, json: Any = None, **params: Any) -> Any:
        return self._request("POST", path, json=json, params=params or None)

    def put(self, path: str, json: Any = None, **params: Any) -> Any:
        return self._request("PUT", path, json=json, params=params or None)

    def delete(self, path: str, **params: Any) -> Any:
        return self._request("DELETE", path, params=params or None)

    def paged(
        self, path: str, params: dict[str, Any] | None = None, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> Iterator[dict]:
        """Iterate every item of a paginated list endpoint.

        XIQ list endpoints take ``?page=&limit=`` (1-based) and respond with
        ``{"page": n, "count": total, "total_pages": N, "data": [...]}``.
        """
        page = 1
        while True:
            merged = dict(params or {})
            merged["page"] = page
            merged["limit"] = limit
            body = self._request("GET", path, params=merged)
            if not isinstance(body, dict):
                # non-paginated endpoint answered with a bare list
                yield from body or []
                return
            data = body.get("data") or []
            yield from data
            total_pages = body.get("total_pages") or 0
            if page >= total_pages or not data:
                return
            page += 1

    # ------------------------------------------------------------------
    # auth
    # ------------------------------------------------------------------
    def _login(self, username: str, password: str) -> None:
        body = self._request(
            "POST", "/login", json={"username": username, "password": password}
        )
        token = (body or {}).get("access_token")
        if not token:
            raise AuthenticationError("Login succeeded but no access_token in response")
        self._set_token(token)

    def logout(self) -> None:
        self._request("POST", "/logout", expect_json=False)
        self.session.headers.pop("Authorization", None)

    def generate_api_token(
        self,
        permissions: Sequence[str],
        *,
        expire_time: int = 0,
        description: str = "generated by xiq-client",
    ) -> dict:
        """Create a long-lived API token (``POST /auth/apitoken``)."""
        return self.post(
            "/auth/apitoken",
            json={
                "permissions": list(permissions),
                "expire_time": expire_time,
                "description": description,
            },
        )

    def token_info(self) -> dict:
        return self.get("/auth/apitoken/info")

    # ------------------------------------------------------------------
    # account / VIQ context
    # ------------------------------------------------------------------
    def account_home(self) -> dict:
        return self.get("/account/home")

    def external_accounts(self) -> list[dict]:
        return self.get("/account/external")

    def switch_account(self, viq_id: int) -> None:
        """Switch into an externally managed VIQ; refreshes the bearer token."""
        body = self.post("/account/:switch", id=viq_id)
        token = (body or {}).get("access_token")
        if not token:
            raise AuthenticationError("Account switch returned no access_token")
        self._set_token(token)

    # ------------------------------------------------------------------
    # devices
    # ------------------------------------------------------------------
    def devices(
        self,
        *,
        views: str = "FULL",
        location_id: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        **filters: Any,
    ) -> Iterator[dict]:
        params: dict[str, Any] = {"views": views, **filters}
        if location_id is not None:
            params["locationId"] = location_id
        return self.paged("/devices", params, limit=limit)

    def device(self, device_id: int) -> dict:
        return self.get(f"/devices/{device_id}")

    def reboot_device(self, device_id: int) -> None:
        self.post(f"/devices/{device_id}/:reboot")

    # untested
    #
    # def assign_network_policy(self, policy_id: int, device_ids: Sequence[int]) -> dict:
    #     return self.post(
    #         "/devices/network-policy/:assign",
    #         json={"network_policy_id": policy_id, "devices": {"ids": list(device_ids)}},
    #     )
    #
    # def send_cli(self, device_ids: Sequence[int], commands: Sequence[str]) -> dict:
    #     return self.post(
    #         "/devices/:cli", json={"devices": {"ids": list(device_ids)}, "clis": list(commands)}
    #     )

    # ------------------------------------------------------------------
    # locations
    # ------------------------------------------------------------------
    def locations_tree(self, *, expand_children: bool = True) -> list[dict]:
        return self.get("/locations/tree", expandChildren=expand_children)

    def buildings(self, *, limit: int = DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        return self.paged("/locations/building", limit=limit)

    def floors(self, *, limit: int = DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        return self.paged("/locations/floor", limit=limit)

    # untested
    #
    # def create_building(self, payload: dict) -> dict:
    #     return self.post("/locations/building", json=payload)
    #
    # def create_floor(self, payload: dict) -> dict:
    #     return self.post("/locations/floor", json=payload)

    # ------------------------------------------------------------------
    # end users (PPSK) / user groups / PCGs
    # ------------------------------------------------------------------
    def endusers(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> Iterator[dict]:
        return self.paged("/endusers", dict(filters), limit=limit)

    def create_enduser(self, payload: dict) -> dict:
        return self.post("/endusers", json=payload)

    # untested
    #
    # def update_enduser(self, enduser_id: int, payload: dict) -> dict:
    #     return self.put(f"/endusers/{enduser_id}", json=payload)

    def delete_enduser(self, enduser_id: int) -> None:
        self.delete(f"/endusers/{enduser_id}")

    def usergroups(self, *, limit: int = DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        return self.paged("/usergroups", limit=limit)

    def pcg_users(self, policy_id: int, *, limit: int = DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        return self.paged(f"/pcgs/key-based/network-policy-{policy_id}/users", limit=limit)

    def add_pcg_users(self, policy_id: int, users: Sequence[dict]) -> dict:
        return self.post(
            f"/pcgs/key-based/network-policy-{policy_id}/users", json={"users": list(users)}
        )

    def delete_pcg_users(self, policy_id: int, user_ids: Sequence[int]) -> None:
        # DELETE with a body; the API answers 202
        self._request(
            "DELETE",
            f"/pcgs/key-based/network-policy-{policy_id}/users",
            json={"user_ids": list(user_ids)},
        )

    # ------------------------------------------------------------------
    # network policies / CCGs
    # ------------------------------------------------------------------
    def network_policies(self, *, limit: int = DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        return self.paged("/network-policies", limit=limit)

    def ccgs(self, *, limit: int = DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        return self.paged("/ccgs", limit=limit)

    # untested
    #
    # def create_ccg(self, payload: dict) -> dict:
    #     return self.post("/ccgs", json=payload)
    #
    # def update_ccg(self, ccg_id: int, payload: dict) -> dict:
    #     return self.put(f"/ccgs/{ccg_id}", json=payload)

    def delete_ccg(self, ccg_id: int) -> None:
        self.delete(f"/ccgs/{ccg_id}")


__all__ = [
    "XIQ",
    "XIQError",
    "XIQ_BASE_URL",
    "PLATFORM_ONE_BASE_URL",
]
