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
from typing import Any, BinaryIO, Callable

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
            self._warn_token_platform_mismatch(token)
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

    def _warn_token_platform_mismatch(self, token: str) -> None:
        # XIQ and Platform ONE credentials are created separately and are not
        # interchangeable: Platform ONE API keys start with "extr_sk_", classic
        # XIQ tokens are JWTs. Catch obvious cross-wiring before the first 401.
        is_p1_key = token.startswith("extr_sk_")
        is_xiq_jwt = token.startswith("ey") and token.count(".") == 2
        on_p1 = self.base_url == PLATFORM_ONE_BASE_URL
        if is_p1_key and not on_p1:
            logger.warning(
                "token looks like a Platform ONE API key (extr_sk_...) but base_url "
                "is %s; pass base_url=PLATFORM_ONE_BASE_URL or use an XIQ token",
                self.base_url,
            )
        elif is_xiq_jwt and on_p1:
            logger.warning(
                "token looks like a classic XIQ token (JWT) but base_url is the "
                "Platform ONE endpoint; Platform ONE API keys start with extr_sk_"
            )

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
        """
        # absolute URLs pass through untouched (e.g. LRO Location URLs)
        if path.startswith(("http://", "https://")):
            url = path
        else:
            url = self.base_url + "/" + path.lstrip("/")
        last_exc: Exception | None = None
        response: requests.Response | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.request(
                    method, url, params=params, json=json, data=data,
                    files=files, timeout=self.timeout,
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
            return self._finish(method, url, response, expect_json, raw, return_location)

        if response is not None:
            # retries exhausted on a retryable status
            return self._finish(method, url, response, expect_json, raw, return_location)
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
        """Poll a long-running operation's Location URL from :meth:`post_lro`."""
        return self._request("GET", url)

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

    def viq_info(self) -> dict:
        return self.get("/account/viq")

    def viq_backup(self) -> Any:
        return self.post("/account/viq/:backup")

    def viq_export(self) -> str | None:
        """Start a VIQ export; returns the LRO Location URL to poll."""
        return self.post_lro("/account/viq/export")

    def viq_download(self, report_name: str) -> bytes:
        return self._request(
            "GET", "/account/viq/download", params={"reportName": report_name}, raw=True
        )

    def viq_import(
        self, file: BinaryIO, filename: str, *, resend_user_notifications: bool = False
    ) -> str | None:
        """Import a VIQ backup file; returns the LRO Location URL to poll."""
        params = {"resendUserNotifications": "true"} if resend_user_notifications else None
        files = {"importFile": (filename, file, "text/plain")}
        return self.post_lro("/account/viq/import", params=params, files=files)

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

    def delete_device(self, device_id: int) -> None:
        self.delete(f"/devices/{device_id}")

    def delete_devices(self, device_ids: Sequence[int]) -> Any:
        return self.post("/devices/:delete", json={"ids": list(device_ids)})

    def unmanage_devices(self, device_ids: Sequence[int]) -> Any:
        return self.post("/devices/:unmanage", json={"ids": list(device_ids)})

    def onboard_devices(self, payload: dict) -> Any:
        return self.post("/devices/:onboard", json=payload)

    def advanced_onboard(self, payload: dict, *, wait: bool = True) -> Any:
        """Advanced onboard. ``wait=False`` runs async and returns the LRO URL."""
        params = {"async": "false" if wait else "true"}
        if wait:
            return self._request(
                "POST", "/devices/:advanced-onboard", json=payload, params=params
            )
        return self.post_lro("/devices/:advanced-onboard", json=payload, params=params)

    def reboot_device(self, device_id: int) -> None:
        self.post(f"/devices/{device_id}/:reboot")

    def send_cli(self, device_ids: Sequence[int], commands: Sequence[str]) -> dict:
        return self._request(
            "POST",
            "/devices/:cli",
            params={"async": "false"},
            json={"devices": {"ids": list(device_ids)}, "clis": list(commands)},
        )

    def set_hostname(self, device_id: int, hostname: str) -> Any:
        # the new name goes in the query string, not the body
        return self.put(f"/devices/{device_id}/hostname", hostname=hostname)

    def set_description(self, device_id: int, description: str) -> Any:
        # the API takes the bare string as the body, not JSON
        return self._request("PUT", f"/devices/{device_id}/description", data=description)

    def device_location(self, device_id: int) -> dict:
        return self.get(f"/devices/{device_id}/location")

    def set_device_location(self, device_id: int, payload: dict) -> Any:
        return self.put(f"/devices/{device_id}/location", json=payload)

    def assign_location(self, payload: dict) -> Any:
        return self.post("/devices/location/:assign", json=payload)

    def device_network_policy(self, device_id: int) -> dict:
        return self.get(f"/devices/{device_id}/network-policy")

    def set_device_network_policy(self, device_id: int, payload: dict) -> Any:
        return self.put(f"/devices/{device_id}/network-policy", json=payload)

    def assign_network_policy(self, payload: dict) -> Any:
        return self.post("/devices/network-policy/:assign", json=payload)

    def device_alarms(self, device_id: int, *, limit: int = DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        return self.paged(f"/devices/{device_id}/alarms", limit=limit)

    def wifi_interfaces(self, device_id: int) -> Any:
        return self.get(f"/devices/{device_id}/interfaces/wifi")

    def radio_information(
        self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any
    ) -> Iterator[dict]:
        return self.paged("/devices/radio-information", dict(filters), limit=limit)

    # ------------------------------------------------------------------
    # locations
    # ------------------------------------------------------------------
    def locations_tree(self, *, expand_children: bool = True) -> list[dict]:
        return self.get("/locations/tree", expandChildren=expand_children)

    def init_location(self, organization: str, country: str) -> dict:
        return self.post(
            "/locations/:init", json={"organization": organization, "country": country}
        )

    def create_location(self, payload: dict) -> dict:
        return self.post("/locations", json=payload)

    def sites(self, *, limit: int = DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        return self.paged("/locations/site", limit=limit)

    def create_site(self, payload: dict) -> dict:
        return self.post("/locations/site", json=payload)

    def update_site(self, site_id: int, payload: dict) -> dict:
        return self.put(f"/locations/site/{site_id}", json=payload)

    def buildings(self, *, limit: int = DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        return self.paged("/locations/building", limit=limit)

    def create_building(self, payload: dict) -> dict:
        return self.post("/locations/building", json=payload)

    def floors(self, *, limit: int = DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        return self.paged("/locations/floor", limit=limit)

    def create_floor(self, payload: dict) -> dict:
        return self.post("/locations/floor", json=payload)

    def upload_floorplan(
        self, file: BinaryIO, filename: str, *, content_type: str = "image/png"
    ) -> Any:
        files = {"file": (filename, file, content_type), "type": content_type}
        return self._request("POST", "/locations/floorplan", files=files)

    def countries(self) -> Any:
        return self.get("/countries")

    def validate_country(self, country_code: str) -> Any:
        return self.get(f"/countries/{country_code}/:validate")

    # ------------------------------------------------------------------
    # end users (PPSK) / user groups / PCGs
    # ------------------------------------------------------------------
    def endusers(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> Iterator[dict]:
        return self.paged("/endusers", dict(filters), limit=limit)

    def create_enduser(self, payload: dict) -> dict:
        return self.post("/endusers", json=payload)

    def update_enduser(self, enduser_id: int, payload: dict) -> dict:
        return self.put(f"/endusers/{enduser_id}", json=payload)

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
    # network policies / deployments / SSIDs
    # ------------------------------------------------------------------
    def network_policies(self, *, limit: int = DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        return self.paged("/network-policies", limit=limit)

    def deploy_config(
        self,
        device_ids: Sequence[int],
        *,
        complete_update: bool = False,
        activate_at_next_reboot: bool = False,
        activation_delay_seconds: int = 0,
    ) -> Any:
        """Push a config update to devices (``POST /deployments?async=true``)."""
        return self._request(
            "POST",
            "/deployments",
            params={"async": "true"},
            json={
                "devices": {"ids": list(device_ids)},
                "policy": {
                    "enable_complete_configuration_update": complete_update,
                    "firmware_activate_option": {
                        "enable_activate_at_next_reboot": activate_at_next_reboot,
                        "activation_delay_seconds": activation_delay_seconds,
                    },
                },
            },
        )

    def set_psk_password(self, ssid_id: int, password: str) -> Any:
        # the API takes the bare string as the body, not JSON
        return self._request("PUT", f"/ssids/{ssid_id}/psk/password", data=password)

    # ------------------------------------------------------------------
    # CCGs (cloud config groups)
    # ------------------------------------------------------------------
    def ccgs(self, *, limit: int = DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        return self.paged("/ccgs", limit=limit)

    def create_ccg(self, payload: dict) -> dict:
        return self.post("/ccgs", json=payload)

    def update_ccg(self, ccg_id: int, payload: dict) -> dict:
        return self.put(f"/ccgs/{ccg_id}", json=payload)

    def delete_ccg(self, ccg_id: int) -> None:
        self.delete(f"/ccgs/{ccg_id}")

    # ------------------------------------------------------------------
    # radio profiles
    # ------------------------------------------------------------------
    def radio_profiles(self, *, limit: int = DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        return self.paged("/radio-profiles", limit=limit)

    def radio_usage_opt(self, profile_id: int) -> dict:
        return self.get(f"/radio-profiles/radio-usage-opt/{profile_id}")

    def channel_selection(self, profile_id: int) -> dict:
        return self.get(f"/radio-profiles/channel-selection/{profile_id}")

    # ------------------------------------------------------------------
    # firewall / network objects
    # ------------------------------------------------------------------
    def ip_firewall_policies(self, *, limit: int = DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        return self.paged("/ip-firewall-policies", limit=limit)

    def create_ip_firewall_policy(self, payload: dict) -> dict:
        return self.post("/ip-firewall-policies", json=payload)

    def update_ip_firewall_policy(self, policy_id: int, payload: dict) -> dict:
        return self.put(f"/ip-firewall-policies/{policy_id}", json=payload)

    def delete_ip_firewall_policy(self, policy_id: int) -> None:
        self.delete(f"/ip-firewall-policies/{policy_id}")

    def l3_address_profiles(
        self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any
    ) -> Iterator[dict]:
        return self.paged("/l3-address-profiles", dict(filters), limit=limit)

    def create_l3_address_profile(self, payload: dict) -> dict:
        return self.post("/l3-address-profiles", json=payload)

    def network_services(
        self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any
    ) -> Iterator[dict]:
        return self.paged("/network-services", dict(filters), limit=limit)

    # ------------------------------------------------------------------
    # admin users / credential distribution groups
    # ------------------------------------------------------------------
    def users(self, *, limit: int = DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        return self.paged("/users", limit=limit)

    def user(self, user_id: int) -> dict:
        return self.get(f"/users/{user_id}")

    def create_user(self, payload: dict) -> dict:
        return self.post("/users", json=payload)

    def external_users(self, *, limit: int = DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        return self.paged("/users/external", limit=limit)

    def create_external_user(self, payload: dict) -> dict:
        return self.post("/users/external", json=payload)

    def cdgs(self, *, limit: int = DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        return self.paged("/credential-distribution-groups", limit=limit)

    def update_cdg(self, cdg_id: int, payload: dict) -> dict:
        return self.put(f"/credential-distribution-groups/{cdg_id}", json=payload)

    # ------------------------------------------------------------------
    # logs
    # ------------------------------------------------------------------
    def audit_logs(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> Iterator[dict]:
        return self.paged("/logs/audit", dict(filters), limit=limit)


__all__ = [
    "XIQ",
    "XIQError",
    "XIQ_BASE_URL",
    "PLATFORM_ONE_BASE_URL",
]
