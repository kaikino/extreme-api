"""ExtremeCloud IQ API client.

The class is named ``XIQ`` to match the ``xiq_api.py`` copies it replaces.
Every public method's docstring starts with the API call it makes;
``METHODS.md`` is generated from those lines.
"""
from __future__ import annotations

import getpass as _getpass
import json
import mimetypes
import numbers
import os
import time
from collections.abc import Sequence
from typing import Any, BinaryIO, Callable

import requests

from ._http import (
    DEFAULT_LRO_TIMEOUT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_PAGE_SIZE,
    DEFAULT_TIMEOUT,
    BaseClient,
    PollCallback,
    ProgressCallback,
    logger,
)
from .exceptions import (
    AmbiguousNameError,
    APIError,
    AuthenticationError,
    CredentialsError,
    NotFoundError,
)
from .lro import LROState

#: ExtremeCloud IQ API endpoint (classic)
XIQ_BASE_URL = "https://api.extremecloudiq.com"
#: Extreme Platform ONE API endpoint
PLATFORM_ONE_BASE_URL = "https://cloudapi.extremecloudiq.com/xiq/v1"

ENV_TOKEN = "XIQ_API_TOKEN"
ENV_TOKEN_LEGACY = "XIQ_TOKEN"  # accepted as a fallback; prefer XIQ_API_TOKEN
ENV_USERNAME = "XIQ_USERNAME"
ENV_PASSWORD = "XIQ_PASSWORD"
ENV_BASE_URL = "XIQ_BASE_URL"

DEFAULT_VIEWS = "FULL"
DEFAULT_CLI_LRO_TIMEOUT = 1200.0  # CLI on many devices; org scripts waited ~20 min
DEFAULT_CLI_INTERVAL = 15.0
DEFAULT_CLI_INITIAL_DELAY = 5.0
DEFAULT_ONBOARD_TIMEOUT = 900.0
DEFAULT_VIQ_LRO_TIMEOUT = 1800.0
RADIO_INFORMATION_CHUNK = 50  # /devices/radio-information accepts at most 50 ids
SITE_READ_ONLY_FIELDS = (
    "id", "create_time", "update_time", "org_id", "unique_name", "type", "address",
)
CDG_MAX_RESTRICT_NUMBER = 99999
_UNSET: Any = object()


def _package_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("xiq-client")
        except PackageNotFoundError:
            return "0.1.3"
    except ImportError:
        return "0"


def _load_dotenv() -> None:
    # .env is read from the current working directory only, and never
    # overrides real environment variables. Needs the ``dotenv`` extra.
    try:
        from pathlib import Path

        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path.cwd() / ".env")


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (str, bytes, dict)):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def _is_int(value: Any) -> bool:
    # numpy/pandas integers are not ``int`` but are ``numbers.Integral``; bool is excluded
    return isinstance(value, numbers.Integral) and not isinstance(value, bool)


def _drop_none(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if v is not None}


def _exact(items: Sequence[dict], name: str, key: str = "name") -> list[dict]:
    return [item for item in items if item.get(key) == name]


class XIQ(BaseClient):
    """ExtremeCloud IQ / Extreme Platform ONE API client.

    All constructor arguments are keyword-only. Credentials resolve in this
    order: explicit ``token=`` / ``username=`` + ``password=``, then the
    ``XIQ_API_TOKEN`` (or ``XIQ_USERNAME`` / ``XIQ_PASSWORD``) environment
    variables, then a ``.env`` file in the working directory.

    Examples
    --------
    >>> xiq = XIQ()                                   # token from XIQ_API_TOKEN
    >>> xiq = XIQ(token="extr_sk_...")                # explicit token
    >>> xiq = XIQ(username="u", password="p")         # POST /login each run
    >>> xiq = XIQ.from_prompt()                       # env, else Email/Password prompt
    >>> xiq = XIQ(progress=True)                      # "page 2 of 7" lines on stderr
    >>> from xiq_client import PLATFORM_ONE_BASE_URL
    >>> xiq = XIQ(base_url=PLATFORM_ONE_BASE_URL)     # Platform ONE endpoint
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        user_name: str | None = None,
        base_url: str | None = None,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        session: requests.Session | None = None,
        progress: bool | ProgressCallback = False,
        retry_unsafe: bool = False,
    ) -> None:
        _load_dotenv()
        super().__init__(
            base_url=base_url or os.environ.get(ENV_BASE_URL) or XIQ_BASE_URL,
            timeout=timeout,
            max_retries=max_retries,
            session=session,
            progress=progress,
            retry_unsafe=retry_unsafe,
            user_agent=f"xiq-client/{_package_version()}",
        )
        self.viq_name: str | None = None
        self.viq_id: Any = None

        token = token or os.environ.get(ENV_TOKEN) or os.environ.get(ENV_TOKEN_LEGACY) or None
        username = username or user_name or os.environ.get(ENV_USERNAME) or None
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
    # construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def from_prompt(
        cls,
        *,
        token: str | None = None,
        attempts: int = 3,
        input_fn: Callable[[str], str] = input,
        getpass_fn: Callable[[str], str] | None = None,
        print_fn: Callable[[str], None] = print,
        **kwargs: Any,
    ) -> XIQ:
        """Build a client from the environment, else prompt for Email/Password.

        Uses ``token`` / ``XIQ_API_TOKEN`` / ``XIQ_USERNAME``+``XIQ_PASSWORD``
        when available, otherwise asks on the terminal (up to ``attempts``
        times on a failed login). Extra keyword arguments go to ``XIQ()``.
        """
        _load_dotenv()
        token = token or os.environ.get(ENV_TOKEN) or os.environ.get(ENV_TOKEN_LEGACY)
        if token:
            return cls(token=token, **kwargs)
        env_user = os.environ.get(ENV_USERNAME)
        env_pass = os.environ.get(ENV_PASSWORD)
        if env_user and env_pass:
            return cls(username=env_user, password=env_pass, **kwargs)

        ask_password = getpass_fn or _getpass.getpass
        last: Exception | None = None
        for _ in range(max(1, attempts)):
            print_fn("Enter your XIQ login credentials")
            username = input_fn("Email: ").strip()
            password = ask_password("Password: ")
            if not username or not password:
                print_fn("Email and password are both required.")
                continue
            try:
                return cls(username=username, password=password, **kwargs)
            except AuthenticationError as exc:
                last = exc
                print_fn(f"Login failed: {exc.error_message or exc}")
        raise CredentialsError(f"Login failed after {attempts} attempt(s)") from last

    def for_account(self, viq_id: int, viq_name: str | None = None) -> XIQ:
        """A new client switched into ``viq_id``; this client stays on its VIQ."""
        clone = XIQ(
            token=self.token,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=self.max_retries,
            progress=self.progress,
            retry_unsafe=self.retry_unsafe,
        )
        clone.switch_account(viq_id, viq_name)
        return clone

    # pickling: drop the session, keep the token (multiprocessing workers)
    def __getstate__(self) -> dict:
        state = dict(self.__dict__)
        state.pop("session", None)
        state.pop("_sleep", None)
        if callable(state.get("progress")):
            state["progress"] = False
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        self._sleep = time.sleep
        self.session = self._new_session()
        self.session.headers.setdefault("Accept", "application/json")
        if self._token:
            self._set_token(self._token)

    def _warn_token_platform_mismatch(self, token: str) -> None:
        # Platform ONE keys (extr_sk_...) work with either base URL.
        # Classic XIQ tokens from /login (JWT) or /auth/apitoken work only
        # with api.extremecloudiq.com.
        is_xiq_jwt = token.startswith("ey") and token.count(".") == 2
        if is_xiq_jwt and self.base_url == PLATFORM_ONE_BASE_URL:
            logger.warning(
                "token looks like a classic XIQ token (JWT) but base_url is the "
                "Platform ONE endpoint; XIQ /login and /auth/apitoken credentials "
                "work only with %s. Use a Platform ONE key (extr_sk_...) or the "
                "default XIQ endpoint.",
                XIQ_BASE_URL,
            )

    # ------------------------------------------------------------------
    # by-name lookup helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _one(kind: str, name: str, matches: list[dict], candidates: Sequence[dict] = ()) -> dict:
        if len(matches) == 1:
            return matches[0]
        if not matches:
            similar = sorted({str(c.get("name")) for c in candidates if c.get("name")})
            hint = f"; similar names: {', '.join(similar)}" if similar else ""
            raise NotFoundError(f"no {kind} named {name!r}{hint}")
        names = ", ".join(str(m.get("id")) for m in matches)
        raise AmbiguousNameError(
            f"{len(matches)} {kind}s named {name!r} (ids {names})", matches=matches
        )

    # ------------------------------------------------------------------
    # auth
    # ------------------------------------------------------------------
    def _login(self, username: str, password: str) -> None:
        body = self._request(
            "POST", "/login", json={"username": username, "password": password}
        )
        token = (body or {}).get("access_token") if isinstance(body, dict) else None
        if not token:
            raise AuthenticationError("Login succeeded but no access_token in response")
        self._set_token(token)

    def logout(self) -> None:
        """POST /logout — revoke the current token."""
        self._request("POST", "/logout", expect_json=False)
        self.session.headers.pop("Authorization", None)
        self._token = None

    def generate_api_token(
        self,
        permissions: Sequence[str],
        *,
        expire_time: int = 0,
        description: str = "generated by xiq-client",
    ) -> dict:
        """POST /auth/apitoken — create a long-lived API token."""
        return self.post(
            "/auth/apitoken",
            json={
                "permissions": list(permissions),
                "expire_time": expire_time,
                "description": description,
            },
        )

    def token_info(self) -> dict:
        """GET /auth/apitoken/info — metadata for the current token."""
        return self.get("/auth/apitoken/info")

    # ------------------------------------------------------------------
    # account / VIQ context
    # ------------------------------------------------------------------
    def account_home(self) -> dict:
        """GET /account/home — the current VIQ (also sets ``viq_name`` / ``viq_id``)."""
        home = self.get("/account/home")
        if isinstance(home, dict):
            self.viq_name = home.get("name")
            self.viq_id = home.get("id")
        return home

    def external_accounts(self) -> list[dict]:
        """GET /account/external — VIQs this admin can switch into (``[]`` if none)."""
        body = self.get("/account/external")
        return body if isinstance(body, list) else []

    def select_managed_account(self) -> tuple[list[dict], str | None]:
        """GET /account/home + GET /account/external — ``(accounts, home_viq_name)``.

        ``accounts`` is ``[]`` when there are no external accounts or the
        account is not allowed to list them; it never raises for that case.
        """
        home = self.account_home()
        try:
            accounts = self.external_accounts()
        except APIError as exc:
            logger.info("GET /account/external unavailable (%s); no external accounts", exc)
            accounts = []
        return accounts, home.get("name") if isinstance(home, dict) else None

    def switch_account(self, viq_id: int, viq_name: str | None = None) -> str | None:
        """POST /account/:switch — switch into an external VIQ; returns its name.

        The bearer token is replaced. If ``viq_name`` is given, the new
        ``/account/home`` name must match.
        """
        body = self.post("/account/:switch", id=viq_id)
        token = (body or {}).get("access_token") if isinstance(body, dict) else None
        if not token:
            raise AuthenticationError("Account switch returned no access_token")
        self._set_token(token)
        home = self.account_home()
        if viq_name is not None and home.get("name") != viq_name:
            raise AuthenticationError(
                f"Account switch targeted {viq_name!r} but current VIQ is {home.get('name')!r}"
            )
        return self.viq_name

    def choose_account(
        self,
        *,
        accounts: Sequence[dict] | None = None,
        home: str | None = None,
        input_fn: Callable[[str], str] = input,
        print_fn: Callable[[str], None] = print,
        title: str = "Which VIQ would you like to run this script against?",
    ) -> str | None:
        """Interactive VIQ picker; switches into the choice and returns its name.

        With no external accounts it returns the home VIQ name without
        prompting. Pass ``accounts`` / ``home`` from an earlier
        :meth:`select_managed_account` call to avoid fetching them again.
        Replaces the numbered-menu block the org scripts copy.
        """
        if accounts is None:
            accounts, home = self.select_managed_account()
        elif home is None:
            home = self.viq_name or (self.account_home() or {}).get("name")
        accounts = list(accounts)
        if not accounts:
            return home
        while True:
            print_fn(f"\n{title}")
            for index, account in enumerate(accounts):
                print_fn(f"   {index}. {account.get('name')}")
            print_fn(f"   {len(accounts)}. {home} (your main account)\n")
            answer = input_fn(f"Please enter 0 - {len(accounts)}: ").strip()
            try:
                selection = int(answer)
            except ValueError:
                print_fn("Please enter a valid number.")
                continue
            if selection == len(accounts):
                return home
            if 0 <= selection < len(accounts):
                chosen = accounts[selection]
                return self.switch_account(chosen["id"], chosen.get("name"))
            print_fn("Please enter a valid number.")

    def viq_info(self) -> dict:
        """GET /account/viq."""
        return self.get("/account/viq")

    def viq_backup(self) -> Any:
        """POST /account/viq/:backup."""
        return self.post("/account/viq/:backup")

    def viq_export(
        self,
        *,
        wait: bool = False,
        timeout: float = DEFAULT_VIQ_LRO_TIMEOUT,
        interval: float = 30.0,
        on_poll: PollCallback | None = None,
    ) -> Any:
        """POST (LRO) /account/viq/export — start a VIQ export.

        ``wait=False`` returns the LRO Location URL; ``wait=True`` polls and
        returns the finished response (``export_file_name`` etc.).
        """
        url = self.post_lro("/account/viq/export")
        if not wait:
            return url
        return self._finish_lro(url, "/account/viq/export", timeout, interval, on_poll)

    def viq_download(self, report_name: str) -> bytes:
        """GET (bytes) /account/viq/download?reportName=."""
        return self._request(
            "GET", "/account/viq/download", params={"reportName": report_name}, raw=True
        )

    def viq_import(
        self,
        file: BinaryIO | str,
        filename: str | None = None,
        *,
        resend_user_notifications: bool = False,
        wait: bool = False,
        timeout: float = DEFAULT_VIQ_LRO_TIMEOUT,
        interval: float = 30.0,
        on_poll: PollCallback | None = None,
    ) -> Any:
        """POST (LRO, multipart) /account/viq/import — import a VIQ backup.

        ``file`` may be a path or an open binary file. ``wait=False`` returns
        the LRO Location URL; ``wait=True`` returns the finished response.
        """
        if isinstance(file, str):
            filename = filename or os.path.basename(file)
            with open(file, "rb") as fh:
                return self.viq_import(
                    fh, filename, resend_user_notifications=resend_user_notifications,
                    wait=wait, timeout=timeout, interval=interval, on_poll=on_poll,
                )
        if not filename:
            raise ValueError("filename is required when file is not a path")
        params = {"resendUserNotifications": "true"} if resend_user_notifications else None
        files = {"importFile": (filename, file, "text/plain")}
        url = self.post_lro("/account/viq/import", params=params, files=files)
        if not wait:
            return url
        return self._finish_lro(url, "/account/viq/import", timeout, interval, on_poll)

    def _finish_lro(
        self,
        url: str | None,
        path: str,
        timeout: float,
        interval: float,
        on_poll: PollCallback | None,
        *,
        initial_delay: float = 0.0,
        raise_on_failure: bool = True,
    ) -> LROState:
        if not url:
            raise APIError(f"{path} returned no Location header", method="POST", url=path)
        return self.wait_lro(
            url, timeout=timeout, interval=interval, initial_delay=initial_delay,
            on_poll=on_poll, raise_on_failure=raise_on_failure,
        )

    # ------------------------------------------------------------------
    # devices
    # ------------------------------------------------------------------
    def devices(
        self,
        *,
        views: str | None = _UNSET,
        fields: str | Sequence[str] | None = None,
        location_id: int | None = None,
        location_ids: Sequence[int] | None = None,
        hostnames: str | Sequence[str] | None = None,
        mac_addresses: str | Sequence[str] | None = None,
        serials: str | Sequence[str] | None = None,
        connected: bool | None = None,
        config_mismatch: bool | None = None,
        admin_states: str | Sequence[str] | None = None,
        device_types: str | Sequence[str] | None = None,
        null_field: str | None = None,
        device_function: str | None = None,
        order: str | None = None,
        sort_field: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        **filters: Any,
    ) -> list[dict]:
        """GET (paged) /devices — every device matching the filters.

        List filters are sent as repeated query params. ``views`` defaults
        to ``FULL`` unless ``fields`` is given (then only ``fields`` is
        sent). ``device_function`` (``"AP"``, ``"SWITCH"``, ...) is filtered
        client-side; the API has no such parameter. Unknown keyword
        arguments pass through as raw query parameters.
        """
        params: dict[str, Any] = dict(filters)
        if views is _UNSET:
            views = None if fields else DEFAULT_VIEWS
        if views:
            params["views"] = views
        if fields:
            params["fields"] = _as_list(fields)
        if location_id is not None:
            params["locationId"] = location_id
        if location_ids:
            params["locationIds"] = list(location_ids)
        if hostnames is not None:
            params["hostnames"] = _as_list(hostnames)
        if mac_addresses is not None:
            params["macAddresses"] = _as_list(mac_addresses)
        if serials:
            params["sns"] = _as_list(serials)
        if connected is not None:
            params["connected"] = connected
        if config_mismatch is not None:
            params["configMismatch"] = config_mismatch
        if admin_states:
            params["adminStates"] = _as_list(admin_states)
        if device_types:
            params["deviceTypes"] = _as_list(device_types)
        if null_field:
            params["nullField"] = null_field
        if order:
            params["order"] = order
        if sort_field:
            params["sortField"] = sort_field
        found = self._list("/devices", params, limit=limit)
        if device_function:
            wanted = device_function.upper()
            found = [d for d in found if str(d.get("device_function", "")).upper() == wanted]
        return found

    def device_count(self, **filters: Any) -> int:
        """GET /devices?limit=1 — total device count for the filters (one request)."""
        return self.count("/devices", **filters)

    def device(self, device_id: int, **params: Any) -> dict:
        """GET /devices/{id} — extra query params (e.g. ``fields="CONNECTED"``) pass through."""
        return self.get(f"/devices/{device_id}", **params)

    def device_by_serial(self, serial: str) -> dict | None:
        """GET /devices?sns= — the device with this serial number, or None."""
        matches = _exact(self.devices(serials=[serial]), serial, "serial_number")
        return matches[0] if matches else None

    def device_by_hostname(self, hostname: str) -> dict | None:
        """GET /devices?hostnames= — the device with exactly this hostname, or None."""
        matches = _exact(self.devices(hostnames=[hostname]), hostname, "hostname")
        return matches[0] if matches else None

    def delete_device(self, device_id: int) -> None:
        """DELETE /devices/{id}."""
        self.delete(f"/devices/{device_id}")

    def delete_devices(self, device_ids: Sequence[int]) -> Any:
        """POST /devices/:delete."""
        return self.post("/devices/:delete", json={"ids": list(device_ids)})

    def unmanage_devices(self, device_ids: Sequence[int]) -> Any:
        """POST /devices/:unmanage."""
        return self.post("/devices/:unmanage", json={"ids": list(device_ids)})

    def onboard_devices(self, payload: dict) -> Any:
        """POST /devices/:onboard."""
        return self.post("/devices/:onboard", json=payload)

    def advanced_onboard(
        self,
        payload: dict | None = None,
        *,
        extreme: Sequence[Any] = (),
        exos: Sequence[Any] = (),
        voss: Sequence[Any] = (),
        unmanaged: bool = False,
        wait: bool = True,
        timeout: float = DEFAULT_ONBOARD_TIMEOUT,
        interval: float = 15.0,
        on_poll: PollCallback | None = None,
    ) -> Any:
        """POST (LRO) /devices/:advanced-onboard — onboard by serial number.

        Pass a full ``payload`` dict, or the ``extreme`` / ``exos`` / ``voss``
        lists and ``unmanaged`` flag. ``wait=True`` polls the LRO and returns
        its response (``success_devices`` / ``failure_devices``);
        ``wait=False`` returns the LRO Location URL.
        """
        if payload is None:
            payload = {
                "extreme": list(extreme),
                "exos": list(exos),
                "voss": list(voss),
                "unmanaged": unmanaged,
            }
        url = self.post_lro("/devices/:advanced-onboard", json=payload, params={"async": "true"})
        if not wait:
            return url
        state = self._finish_lro(url, "/devices/:advanced-onboard", timeout, interval, on_poll)
        return state.response if state.response is not None else state.body

    def reboot_device(self, device_id: int) -> Any:
        """POST /devices/{id}/:reboot."""
        return self.post(f"/devices/{device_id}/:reboot")

    def wait_for_device_connected(
        self,
        device_id: int,
        *,
        timeout: float = 600.0,
        interval: float = 30.0,
        on_poll: Callable[[bool, float], None] | None = None,
    ) -> bool:
        """GET /devices/{id}?fields=CONNECTED until connected or ``timeout``; returns the final
        state.
        """
        start = time.monotonic()
        while True:
            connected = bool((self.device(device_id, fields="CONNECTED") or {}).get("connected"))
            elapsed = time.monotonic() - start
            self._report(f"device {device_id} connected={connected} ({elapsed:.0f}s)")
            if on_poll is not None:
                on_poll(connected, elapsed)
            if connected or elapsed >= timeout:
                return connected
            self._sleep(interval)

    def send_cli(
        self,
        device_ids: Sequence[int],
        commands: str | Sequence[str],
        *,
        wait: bool = False,
        timeout: float = DEFAULT_CLI_LRO_TIMEOUT,
        interval: float = DEFAULT_CLI_INTERVAL,
        initial_delay: float = DEFAULT_CLI_INITIAL_DELAY,
        on_poll: PollCallback | None = None,
    ) -> dict:
        """POST /devices/:cli — run CLI commands on devices.

        ``wait=False`` runs synchronously (``async=false``); ``wait=True``
        starts an LRO (``async=true``) and polls it. Either way the result is
        ``{"device_cli_outputs": {"<device id>": [{"cli", "output",
        "response_code"}, ...]}}``. See :meth:`cli_outputs`.
        """
        payload = {"devices": {"ids": list(device_ids)}, "clis": _as_list(commands)}
        if not wait:
            body = self._request(
                "POST", "/devices/:cli", params={"async": "false"}, json=payload
            )
            return body if isinstance(body, dict) else {"device_cli_outputs": {}}
        url = self.post_lro("/devices/:cli", json=payload, params={"async": "true"})
        state = self._finish_lro(
            url, "/devices/:cli", timeout, interval, on_poll, initial_delay=initial_delay
        )
        body = state.response if isinstance(state.response, dict) else state.body
        return body if isinstance(body, dict) else {"device_cli_outputs": {}}

    @staticmethod
    def cli_outputs(result: dict) -> dict[int, list[dict]]:
        """Flatten a :meth:`send_cli` result to ``{device_id (int): [outputs...]}``."""
        outputs = (result or {}).get("device_cli_outputs") or {}
        flat: dict[int, list[dict]] = {}
        for key, value in outputs.items():
            try:
                device_id = int(key)
            except (TypeError, ValueError):
                continue
            flat[device_id] = list(value or [])
        return flat

    def set_hostname(self, device_id: int, hostname: str) -> Any:
        """PUT /devices/{id}/hostname?hostname= — the new name goes in the query string."""
        return self.put(f"/devices/{device_id}/hostname", hostname=hostname)

    def set_description(self, device_id: int, description: str) -> Any:
        """PUT (raw body) /devices/{id}/description — the body is the bare string."""
        return self._request("PUT", f"/devices/{device_id}/description", data=description)

    def device_location(self, device_id: int) -> dict:
        """GET /devices/{id}/location."""
        return self.get(f"/devices/{device_id}/location")

    def set_device_location(
        self,
        device_id: int,
        payload: dict | int,
        *,
        x: float | None = None,
        y: float | None = None,
        latitude: Any = None,
        longitude: Any = None,
    ) -> Any:
        """PUT /devices/{id}/location — ``payload`` may be a dict or a floor/location id."""
        if not isinstance(payload, dict):
            payload = _drop_none(
                {
                    "location_id": payload, "x": x, "y": y,
                    "latitude": latitude, "longitude": longitude,
                }
            )
        return self.put(f"/devices/{device_id}/location", json=payload)

    def move_device(
        self, device_id: int, location_id: int, *, x: float | None = None, y: float | None = None
    ) -> Any:
        """GET + PUT /devices/{id}/location — move a device, keeping its x/y unless given."""
        current = self.device_location(device_id) or {}
        payload = {
            "location_id": location_id,
            "x": current.get("x", 0) if x is None else x,
            "y": current.get("y", 0) if y is None else y,
        }
        return self.put(f"/devices/{device_id}/location", json=payload)

    def assign_location(
        self,
        devices: dict | Sequence[int],
        location_id: int | None = None,
        *,
        x: float = 0,
        y: float = 0,
        latitude: float = 0,
        longitude: float = 0,
    ) -> Any:
        """POST /devices/location/:assign — ``devices`` is a payload dict or a list of ids."""
        if isinstance(devices, dict):
            payload = devices
        else:
            if location_id is None:
                raise ValueError("location_id is required when passing device ids")
            payload = {
                "devices": {"ids": list(devices)},
                "device_location": {
                    "location_id": location_id, "x": x, "y": y,
                    "latitude": latitude, "longitude": longitude,
                },
            }
        return self.post("/devices/location/:assign", json=payload)

    def device_network_policy(self, device_id: int) -> dict:
        """GET /devices/{id}/network-policy."""
        return self.get(f"/devices/{device_id}/network-policy")

    def set_device_network_policy(
        self,
        device_id: int,
        payload: dict | int | None = None,
        *,
        network_policy_id: int | None = None,
    ) -> Any:
        """PUT /devices/{id}/network-policy?networkPolicyId= — ``payload`` may be the id or a dict.
        """
        if _is_int(payload):
            network_policy_id = payload
        elif network_policy_id is None and isinstance(payload, dict):
            network_policy_id = payload.get("networkPolicyId") or payload.get(
                "network_policy_id"
            )
        if network_policy_id is None:
            raise ValueError("network_policy_id is required")
        return self.put(
            f"/devices/{device_id}/network-policy",
            networkPolicyId=network_policy_id,
        )

    def assign_network_policy(
        self,
        devices: dict | str | Sequence[int],
        network_policy_id: int | None = None,
    ) -> Any:
        """POST /devices/network-policy/:assign — ``devices`` is a list of ids, a dict, or a JSON
        string.
        """
        if isinstance(devices, str):
            payload = json.loads(devices)
        elif isinstance(devices, dict):
            payload = devices
        else:
            if network_policy_id is None:
                raise ValueError("network_policy_id is required when passing device ids")
            payload = {"devices": {"ids": list(devices)}, "network_policy_id": network_policy_id}
        return self.post("/devices/network-policy/:assign", json=payload)

    def device_alarms(
        self, device_id: int, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any
    ) -> list[dict]:
        """GET (paged) /devices/{id}/alarms — pass ``startTime`` / ``endTime`` (epoch ms)."""
        return self._list(f"/devices/{device_id}/alarms", dict(filters), limit=limit)

    def device_alarm_count(self, device_id: int, **filters: Any) -> int:
        """GET /devices/{id}/alarms?limit=1 — alarm count in one request."""
        return self.count(f"/devices/{device_id}/alarms", **filters)

    def wifi_interfaces(self, device_id: int, **params: Any) -> Any:
        """GET /devices/{id}/interfaces/wifi — optional ``startTime`` / ``endTime``; returns the
        list.
        """
        body = self.get(f"/devices/{device_id}/interfaces/wifi", **params)
        if isinstance(body, dict) and isinstance(body.get("data"), list):
            return body["data"]
        return body

    def radio_information(
        self,
        *,
        device_ids: Sequence[int] | None = None,
        include_disabled_radio: bool | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        **filters: Any,
    ) -> list[dict]:
        """GET (paged) /devices/radio-information — ``device_ids`` is chunked to the API's 50-id
        limit.
        """
        params: dict[str, Any] = dict(filters)
        if include_disabled_radio is not None:
            params["includeDisabledRadio"] = include_disabled_radio
        if not device_ids:
            return self._list("/devices/radio-information", params, limit=limit)
        ids = list(device_ids)
        found: list[dict] = []
        for start in range(0, len(ids), RADIO_INFORMATION_CHUNK):
            chunk = ids[start:start + RADIO_INFORMATION_CHUNK]
            chunk_params = dict(params)
            chunk_params["deviceIds"] = ",".join(str(i) for i in chunk)
            found.extend(self._list("/devices/radio-information", chunk_params, limit=limit))
        return found

    # ------------------------------------------------------------------
    # locations
    # ------------------------------------------------------------------
    def locations_tree(
        self, *, expand_children: bool = True, parent_id: int | None = None
    ) -> list[dict]:
        """GET /locations/tree — pass ``parent_id`` to list children of a site/building."""
        params: dict[str, Any] = {"expandChildren": expand_children}
        if parent_id is not None:
            params["parentId"] = parent_id
        body = self.get("/locations/tree", **params)
        return body if isinstance(body, list) else []

    def locations_flat(self) -> list[dict]:
        """GET /locations/tree (walked) — every location as ``{id, name, type, parent_id, path}``.
        """
        flat: list[dict] = []

        def walk(nodes: list[dict], parent_id: int | None, prefix: str) -> None:
            for node in nodes:
                name = str(node.get("name", ""))
                path = f"{prefix} / {name}" if prefix else name
                node_type = str(node.get("type") or "")
                flat.append(
                    {"id": node.get("id"), "name": name, "type": node_type,
                     "parent_id": parent_id, "path": path}
                )
                children = node.get("children")
                if children is None and node_type.upper() != "FLOOR" and node.get("id") is not None:
                    children = self.locations_tree(parent_id=node["id"], expand_children=False)
                if children:
                    walk(children, node.get("id"), path)

        walk(self.locations_tree(expand_children=True), None, "")
        return flat

    def init_location(self, organization: str, country: str) -> dict:
        """POST /locations/:init."""
        return self.post(
            "/locations/:init", json={"organization": organization, "country": country}
        )

    def create_location(self, payload: dict | str, *, parent_id: int | None = None) -> dict:
        """POST /locations — ``payload`` may be a dict or a name (with ``parent_id``)."""
        if isinstance(payload, str):
            payload = _drop_none({"parent_id": parent_id, "name": payload})
        return self.post("/locations", json=payload)

    def sites(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> list[dict]:
        """GET (paged) /locations/site — filters (``name``, ``ids``, ``order``) pass through."""
        return self._list("/locations/site", dict(filters), limit=limit)

    def site_by_name(self, name: str) -> dict | None:
        """GET /locations/site?name= — the site with exactly this name, or None."""
        matches = _exact(self.sites(name=name), name)
        return matches[0] if matches else None

    def site_id(self, name: str) -> int:
        """GET /locations/site?name= — the id of the uniquely named site (raises if 0 or >1)."""
        candidates = self.sites(name=name)
        return self._one("site", name, _exact(candidates, name), candidates)["id"]

    def create_site(self, payload: dict) -> dict:
        """POST /locations/site."""
        return self.post("/locations/site", json=payload)

    def update_site(self, site: dict | int, payload: dict | None = None, **changes: Any) -> dict:
        """PUT /locations/site/{id} — pass the GET shape (read-only keys are stripped) plus changes.
        """
        if isinstance(site, dict):
            site_id = site["id"]
            body = {k: v for k, v in site.items() if k not in SITE_READ_ONLY_FIELDS}
        else:
            site_id = site
            body = {}
        body.update(payload or {})
        body.update(changes)
        return self.put(f"/locations/site/{site_id}", json=body)

    def buildings(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> list[dict]:
        """GET (paged) /locations/building — filters (``name``, ``ids``, ``order``) pass through."""
        return self._list("/locations/building", dict(filters), limit=limit)

    def building_by_name(self, name: str) -> dict | None:
        """GET /locations/building?name= — the building with exactly this name, or None if 0 or >1.
        """
        matches = _exact(self.buildings(name=name), name)
        return matches[0] if len(matches) == 1 else None

    def building_id(self, name: str) -> int:
        """GET /locations/building?name= — the id of the uniquely named building (raises if 0 or
        >1).
        """
        candidates = self.buildings(name=name)
        return self._one("building", name, _exact(candidates, name), candidates)["id"]

    def create_building(self, payload: dict) -> dict:
        """POST /locations/building."""
        return self.post("/locations/building", json=payload)

    def floors(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> list[dict]:
        """GET (paged) /locations/floor."""
        return self._list("/locations/floor", dict(filters), limit=limit)

    def floors_for_building(self, building: str | int) -> list[dict]:
        """GET /locations/building?name= + GET /locations/tree?parentId= — floors of a building.

        ``building`` is an exact name or an id. Raises :class:`NotFoundError`
        (listing similar names) or :class:`AmbiguousNameError`.
        """
        parent_id = int(building) if _is_int(building) else self.building_id(str(building))
        return self.locations_tree(parent_id=parent_id, expand_children=False)

    def floor_ids_for_building(self, building: str | int) -> list[int]:
        """Floor ids of a building (see :meth:`floors_for_building`)."""
        return [floor["id"] for floor in self.floors_for_building(building)]

    def floor_in_building(self, building: str | int, floor_name: str) -> dict:
        """The floor named ``floor_name`` in a building (exact, then case-insensitive match)."""
        floors = self.floors_for_building(building)
        matches = _exact(floors, floor_name)
        if not matches:
            matches = [f for f in floors if str(f.get("name", "")).lower() == floor_name.lower()]
        return self._one("floor", floor_name, matches, floors)

    def floor_ids_for_site(self, site: str | int) -> list[int]:
        """GET /locations/tree walked from a site — every floor id under it."""
        site_id = int(site) if _is_int(site) else self.site_id(str(site))
        floor_ids: list[int] = []
        for building in self.locations_tree(parent_id=site_id, expand_children=False):
            floor_ids.extend(
                f["id"]
                for f in self.locations_tree(parent_id=building["id"], expand_children=False)
            )
        return floor_ids

    def devices_in_site(self, site: str | int, **filters: Any) -> list[dict]:
        """Devices on any floor of a site (see :meth:`devices` for filters)."""
        floor_ids = self.floor_ids_for_site(site)
        if not floor_ids:
            raise NotFoundError(f"site {site!r} has no floors")
        return self.devices(location_ids=floor_ids, **filters)

    def devices_in_building(self, building: str | int, **filters: Any) -> list[dict]:
        """Devices on any floor of a building (see :meth:`devices` for filters)."""
        floor_ids = self.floor_ids_for_building(building)
        if not floor_ids:
            raise NotFoundError(f"building {building!r} has no floors")
        return self.devices(location_ids=floor_ids, **filters)

    def devices_in_floor(self, building: str | int, floor_name: str, **filters: Any) -> list[dict]:
        """Devices on one floor of a building (see :meth:`devices` for filters)."""
        floor = self.floor_in_building(building, floor_name)
        return self.devices(location_id=floor["id"], **filters)

    def create_floor(self, payload: dict) -> dict:
        """POST /locations/floor."""
        return self.post("/locations/floor", json=payload)

    def upload_floorplan(
        self,
        file: BinaryIO | str,
        filename: str | None = None,
        *,
        content_type: str | None = None,
    ) -> Any:
        """POST (multipart) /locations/floorplan — ``file`` may be a path or an open binary file."""
        if isinstance(file, str):
            filename = filename or os.path.basename(file)
            with open(file, "rb") as fh:
                return self.upload_floorplan(fh, filename, content_type=content_type)
        if not filename:
            raise ValueError("filename is required when file is not a path")
        if not content_type:
            content_type = mimetypes.guess_type(filename)[0] or "image/png"
        files = {"file": (filename, file, content_type), "type": (None, content_type)}
        return self._request("POST", "/locations/floorplan", files=files)

    def countries(self) -> list[dict]:
        """GET /countries — the list of country codes."""
        body = self.get("/countries")
        if isinstance(body, dict) and isinstance(body.get("data"), list):
            return body["data"]
        return body if isinstance(body, list) else []

    def validate_country(self, country_code: str) -> bool:
        """GET /countries/{code}/:validate — True when the code is valid."""
        body = self.get(f"/countries/{country_code}/:validate")
        if isinstance(body, bool):
            return body
        if isinstance(body, dict):
            for key in ("valid", "is_valid", "validated"):
                if key in body:
                    return bool(body[key])
            return True
        if isinstance(body, str):
            return body.strip().lower() in ("true", "valid", "ok")
        return bool(body)

    # ------------------------------------------------------------------
    # end users (PPSK) / user groups / PCGs
    # ------------------------------------------------------------------
    def endusers(
        self,
        *,
        user_group_id: int | None = None,
        user_group_ids: Sequence[int] | None = None,
        usernames: str | Sequence[str] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        **filters: Any,
    ) -> list[dict]:
        """GET (paged) /endusers — PPSK users, optionally by group / user name."""
        params: dict[str, Any] = dict(filters)
        ids = list(user_group_ids or [])
        if user_group_id is not None:
            ids.append(user_group_id)
        if ids:
            params["user_group_ids"] = ids
        if usernames:
            params["usernames"] = _as_list(usernames)
        return self._list("/endusers", params, limit=limit)

    def enduser(self, enduser_id: int) -> dict:
        """GET /endusers/{id}."""
        return self.get(f"/endusers/{enduser_id}")

    def enduser_by_username(
        self, user_name: str, *, user_group_id: int | None = None
    ) -> dict | None:
        """GET /endusers?usernames= — the PPSK user with exactly this user name, or None."""
        matches = _exact(
            self.endusers(usernames=[user_name], user_group_id=user_group_id),
            user_name,
            "user_name",
        )
        return matches[0] if matches else None

    def create_enduser(
        self,
        payload: dict | int,
        *,
        name: str | None = None,
        user_name: str | None = None,
        password: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        organization: str | None = None,
        visit_purpose: str | None = None,
        description: str | None = None,
        email_password_delivery: str | None = None,
        sms_password_delivery: str | None = None,
        **extra: Any,
    ) -> dict:
        """POST /endusers — ``payload`` is a dict, or the user group id with keyword fields.

        ``email_password_delivery`` / ``sms_password_delivery`` take the
        destination address, not a flag. ``password=""`` lets XIQ generate one.
        """
        if isinstance(payload, dict):
            return self.post("/endusers", json=payload)
        body = _drop_none(
            {
                "user_group_id": payload,
                "name": name,
                "user_name": user_name or name,
                "password": password,
                "email_address": email,
                "phone_number": phone,
                "organization": organization,
                "visit_purpose": visit_purpose,
                "description": description,
                "email_password_delivery": email_password_delivery,
                "sms_password_delivery": sms_password_delivery,
                **extra,
            }
        )
        if "password" not in body:
            body["password"] = ""
        return self.post("/endusers", json=body)

    def update_enduser(self, enduser_id: int, payload: dict) -> dict:
        """PUT /endusers/{id}."""
        return self.put(f"/endusers/{enduser_id}", json=payload)

    def set_enduser_password(self, enduser_id: int, password: str) -> dict:
        """PUT /endusers/{id} with ``{"password": ...}``; verifies the echoed password."""
        body = self.update_enduser(enduser_id, {"password": password})
        if isinstance(body, dict) and body.get("password") not in (None, password):
            raise APIError(
                f"password for end user {enduser_id} was not applied",
                method="PUT",
                url=f"/endusers/{enduser_id}",
                body=body,
            )
        return body if isinstance(body, dict) else {}

    def delete_enduser(self, enduser_id: int) -> None:
        """DELETE /endusers/{id}."""
        self.delete(f"/endusers/{enduser_id}")

    def usergroups(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> list[dict]:
        """GET (paged) /usergroups."""
        return self._list("/usergroups", dict(filters), limit=limit)

    def usergroup_by_name(self, name: str) -> dict | None:
        """GET /usergroups — the user group with exactly this name, or None."""
        matches = _exact(self.usergroups(), name)
        return matches[0] if matches else None

    def usergroup_id(self, name: str) -> int:
        """GET /usergroups — the id of the uniquely named user group (raises if 0 or >1)."""
        groups = self.usergroups()
        return self._one("user group", name, _exact(groups, name), groups)["id"]

    def pcg_users(self, policy_id: int, *, limit: int = DEFAULT_PAGE_SIZE) -> list[dict]:
        """GET (paged) /pcgs/key-based/network-policy-{id}/users."""
        return self._list(f"/pcgs/key-based/network-policy-{policy_id}/users", limit=limit)

    def add_pcg_users(self, policy_id: int, users: Sequence[dict]) -> dict:
        """POST /pcgs/key-based/network-policy-{id}/users — ``users`` are ``{name, email,
        user_group_name}`` dicts.
        """
        return self.post(
            f"/pcgs/key-based/network-policy-{policy_id}/users", json={"users": list(users)}
        )

    def add_pcg_user(self, policy_id: int, name: str, email: str, user_group_name: str) -> dict:
        """POST /pcgs/key-based/network-policy-{id}/users — add one user."""
        return self.add_pcg_users(
            policy_id, [{"name": name, "email": email, "user_group_name": user_group_name}]
        )

    def delete_pcg_users(self, policy_id: int, user_ids: Sequence[int]) -> None:
        """DELETE /pcgs/key-based/network-policy-{id}/users — DELETE with a JSON body; the API
        answers 202.
        """
        self._request(
            "DELETE",
            f"/pcgs/key-based/network-policy-{policy_id}/users",
            json={"user_ids": list(user_ids)},
        )

    def delete_pcg_user(self, policy_id: int, user_id: int) -> None:
        """DELETE /pcgs/key-based/network-policy-{id}/users — remove one user."""
        self.delete_pcg_users(policy_id, [user_id])

    # ------------------------------------------------------------------
    # network policies / deployments / SSIDs
    # ------------------------------------------------------------------
    def network_policies(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> list[dict]:
        """GET (paged) /network-policies — filters (``policyNames``, ``keyword``) pass through."""
        return self._list("/network-policies", dict(filters), limit=limit)

    def network_policy_by_name(self, name: str) -> dict | None:
        """GET /network-policies?policyNames= — the policy with exactly this name, or None."""
        matches = _exact(self.network_policies(policyNames=name), name)
        return matches[0] if matches else None

    def network_policy_id(self, name: str) -> int:
        """GET /network-policies?policyNames= — the id of the uniquely named policy (raises if 0 or
        >1).
        """
        candidates = self.network_policies(policyNames=name)
        return self._one("network policy", name, _exact(candidates, name), candidates)["id"]

    def deploy_config(
        self,
        device_ids: Sequence[int],
        *,
        complete_update: bool = False,
        activate_at_next_reboot: bool = False,
        activation_delay_seconds: int = 0,
        wait: bool = False,
        timeout: float = DEFAULT_LRO_TIMEOUT,
        interval: float = 10.0,
        on_poll: PollCallback | None = None,
        raise_on_failure: bool = True,
    ) -> Any:
        """POST (LRO) /deployments — push config to devices.

        ``wait=False`` returns the LRO Location URL. ``wait=True`` polls and
        returns the final status string (``SUCCEEDED``, or ``FAILED`` when
        ``raise_on_failure=False``).
        """
        url = self.post_lro(
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
        if not wait:
            return url
        state = self._finish_lro(
            url, "/deployments", timeout, interval, on_poll, raise_on_failure=raise_on_failure
        )
        if state.status:
            return state.status
        return "FAILED" if state.failed else "SUCCEEDED"

    def ssids(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> list[dict]:
        """GET (paged) /ssids."""
        return self._list("/ssids", dict(filters), limit=limit)

    def ssid_by_name(self, name: str) -> dict | None:
        """GET /ssids — the SSID with exactly this name, or None."""
        matches = _exact(self.ssids(), name)
        return matches[0] if matches else None

    def set_psk_password(self, ssid_id: int, password: str) -> Any:
        """PUT (raw body) /ssids/{id}/psk/password — the body is the bare string."""
        return self._request("PUT", f"/ssids/{ssid_id}/psk/password", data=password)

    # ------------------------------------------------------------------
    # CCGs (cloud config groups)
    # ------------------------------------------------------------------
    def ccgs(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> list[dict]:
        """GET (paged) /ccgs."""
        return self._list("/ccgs", dict(filters), limit=limit)

    def ccg(self, ccg_id: int) -> dict:
        """GET /ccgs/{id}."""
        return self.get(f"/ccgs/{ccg_id}")

    def ccg_by_name(self, name: str) -> dict | None:
        """GET /ccgs — the CCG with exactly this name, or None."""
        matches = _exact(self.ccgs(), name)
        return matches[0] if matches else None

    def ccg_id(self, name: str) -> int:
        """GET /ccgs — the id of the uniquely named CCG (raises if 0 or >1)."""
        groups = self.ccgs()
        return self._one("CCG", name, _exact(groups, name), groups)["id"]

    def create_ccg(
        self,
        payload: dict | str,
        *,
        description: str = "",
        device_ids: Sequence[int] = (),
    ) -> dict:
        """POST /ccgs — ``payload`` is a dict, or the name with ``description`` / ``device_ids``."""
        if isinstance(payload, str):
            payload = {"name": payload, "description": description, "device_ids": list(device_ids)}
        return self.post("/ccgs", json=payload)

    def update_ccg(self, ccg_id: int, payload: dict) -> dict:
        """PUT /ccgs/{id} — ``payload`` is ``{name, description, device_ids}``."""
        return self.put(f"/ccgs/{ccg_id}", json=payload)

    def set_ccg_devices(self, ccg_id: int, device_ids: Sequence[int]) -> dict:
        """GET + PUT /ccgs/{id} — replace the CCG's device list."""
        current = self.ccg(ccg_id)
        payload = {
            "name": current.get("name"),
            "description": current.get("description", ""),
            "device_ids": list(device_ids),
        }
        return self.update_ccg(ccg_id, payload)

    def ccg_add_devices(self, ccg_id: int, device_ids: Sequence[int]) -> dict:
        """GET + PUT /ccgs/{id} — add devices to the CCG (keeps existing members)."""
        current = self.ccg(ccg_id)
        existing = list(current.get("device_ids") or [])
        merged = existing + [d for d in device_ids if d not in existing]
        payload = {
            "name": current.get("name"),
            "description": current.get("description", ""),
            "device_ids": merged,
        }
        return self.update_ccg(ccg_id, payload)

    def ccg_remove_devices(self, ccg_id: int, device_ids: Sequence[int]) -> dict:
        """GET + PUT /ccgs/{id} — remove devices from the CCG."""
        current = self.ccg(ccg_id)
        drop = set(device_ids)
        payload = {
            "name": current.get("name"),
            "description": current.get("description", ""),
            "device_ids": [d for d in current.get("device_ids") or [] if d not in drop],
        }
        return self.update_ccg(ccg_id, payload)

    def delete_ccg(self, ccg_id: int) -> None:
        """DELETE /ccgs/{id}."""
        self.delete(f"/ccgs/{ccg_id}")

    # ------------------------------------------------------------------
    # radio profiles
    # ------------------------------------------------------------------
    def radio_profiles(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> list[dict]:
        """GET (paged) /radio-profiles."""
        return self._list("/radio-profiles", dict(filters), limit=limit)

    def radio_profile(self, profile_id: int) -> dict:
        """GET /radio-profiles/{id}."""
        return self.get(f"/radio-profiles/{profile_id}")

    def radio_profile_by_name(self, name: str) -> dict | None:
        """GET /radio-profiles — the profile with exactly this name, or None."""
        matches = _exact(self.radio_profiles(), name)
        return matches[0] if matches else None

    def radio_usage_opt(self, profile_id: int) -> dict:
        """GET /radio-profiles/radio-usage-opt/{id}."""
        return self.get(f"/radio-profiles/radio-usage-opt/{profile_id}")

    def channel_selection(self, profile_id: int) -> dict:
        """GET /radio-profiles/channel-selection/{id}."""
        return self.get(f"/radio-profiles/channel-selection/{profile_id}")

    def radio_profile_details(self, profile: dict | int) -> dict:
        """Radio profile merged with its ``channel_selection`` and ``radio_usage_opt`` sub-objects.
        """
        base = dict(profile) if isinstance(profile, dict) else dict(self.radio_profile(profile))
        profile_id = base["id"]
        details = dict(base)
        details["channel_selection"] = self.channel_selection(profile_id)
        details["radio_usage_opt"] = self.radio_usage_opt(profile_id)
        return details

    # ------------------------------------------------------------------
    # firewall / network objects
    # ------------------------------------------------------------------
    def ip_firewall_policies(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> list[dict]:
        """GET (paged) /ip-firewall-policies."""
        return self._list("/ip-firewall-policies", dict(filters), limit=limit)

    def create_ip_firewall_policy(
        self, payload: dict | str, *, description: str = "", rules: Sequence[dict] = ()
    ) -> dict:
        """POST /ip-firewall-policies — ``payload`` is a dict, or the name with ``rules``."""
        if isinstance(payload, str):
            payload = {"name": payload, "description": description, "rules": list(rules)}
        return self.post("/ip-firewall-policies", json=payload)

    def update_ip_firewall_policy(self, policy_id: int, payload: dict) -> dict:
        """PUT /ip-firewall-policies/{id}."""
        return self.put(f"/ip-firewall-policies/{policy_id}", json=payload)

    def delete_ip_firewall_policy(self, policy_id: int) -> None:
        """DELETE /ip-firewall-policies/{id}."""
        self.delete(f"/ip-firewall-policies/{policy_id}")

    def l3_address_profiles(
        self, *, address_type: str | None = None, limit: int = DEFAULT_PAGE_SIZE, **filters: Any
    ) -> list[dict]:
        """GET (paged) /l3-address-profiles — ``address_type`` is IP_ADDRESS / HOST_NAME / IP_SUBNET
        / IP_RANGE.
        """
        params = dict(filters)
        if address_type:
            params["addressType"] = address_type
        return self._list("/l3-address-profiles", params, limit=limit)

    def create_l3_address_profile(
        self,
        payload: dict | str,
        *,
        address_type: str | None = None,
        value: str | None = None,
        netmask: str | None = None,
        description: str = "",
        **extra: Any,
    ) -> dict:
        """POST /l3-address-profiles — returns the created profile (unwrapped from
        ``*_address_profile``).
        """
        if isinstance(payload, str):
            if not address_type or value is None:
                raise ValueError("address_type and value are required with a name")
            payload = _drop_none(
                {
                    "name": payload,
                    "description": description,
                    "value": value,
                    "netmask": netmask,
                    "address_type": address_type,
                    "enable_classification": False,
                    "classified_entries": [],
                    **extra,
                }
            )
        body = self.post("/l3-address-profiles", json=payload)
        if isinstance(body, dict):
            for key, value_ in body.items():
                if key.endswith("_address_profile") and isinstance(value_, dict):
                    return value_
        return body

    def network_services(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> list[dict]:
        """GET (paged) /network-services — filters (``name``, ``ipProtocol``) pass through."""
        return self._list("/network-services", dict(filters), limit=limit)

    def network_service_by_name(self, name: str) -> dict | None:
        """GET /network-services?name= — the service with exactly this name, or None."""
        matches = _exact(self.network_services(name=name), name)
        return matches[0] if matches else None

    # ------------------------------------------------------------------
    # admin users / credential distribution groups
    # ------------------------------------------------------------------
    def users(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> list[dict]:
        """GET (paged) /users — admin accounts."""
        return self._list("/users", dict(filters), limit=limit)

    def user(self, user_id: int) -> dict:
        """GET /users/{id}."""
        return self.get(f"/users/{user_id}")

    def user_by_login(self, login_name: str) -> dict | None:
        """GET /users — the admin with exactly this login name, or None."""
        matches = _exact(self.users(), login_name, "login_name")
        return matches[0] if matches else None

    def create_user(self, payload: dict) -> dict:
        """POST /users."""
        return self.post("/users", json=payload)

    def create_admin_user(
        self,
        login_name: str,
        display_name: str,
        *,
        role: str = "ADMINISTRATOR",
        idle_timeout: int = 30,
        location_ids: Sequence[int] = (),
        access_scope: int = 0,
        viq_access_control: int = 0,
        **extra: Any,
    ) -> dict:
        """POST /users — create an admin account by keyword."""
        return self.create_user(
            {
                "login_name": login_name,
                "display_name": display_name,
                "idle_timeout": idle_timeout,
                "user_role": role,
                "location_ids": list(location_ids),
                "access_scope": access_scope,
                "viq_access_control": viq_access_control,
                **extra,
            }
        )

    def external_users(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> list[dict]:
        """GET (paged) /users/external — SSO / external admin accounts."""
        return self._list("/users/external", dict(filters), limit=limit)

    def create_external_user(
        self,
        payload: dict | str,
        user_role: str | None = None,
        *,
        org_id: int = 0,
        location_ids: Sequence[int] = (),
        **extra: Any,
    ) -> dict:
        """POST /users/external — ``payload`` is a dict, or the login name with ``user_role``."""
        if isinstance(payload, str):
            if not user_role:
                raise ValueError("user_role is required with a login name")
            payload = {
                "login_name": payload,
                "user_role": user_role,
                "org_id": org_id,
                "location_ids": list(location_ids),
                **extra,
            }
        return self.post("/users/external", json=payload)

    def cdgs(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> list[dict]:
        """GET (paged) /credential-distribution-groups."""
        return self._list("/credential-distribution-groups", dict(filters), limit=limit)

    def cdg(self, cdg_id: int) -> dict:
        """GET /credential-distribution-groups/{id}."""
        return self.get(f"/credential-distribution-groups/{cdg_id}")

    def cdg_by_name(self, name: str) -> dict | None:
        """GET /credential-distribution-groups — the CDG with exactly this name, or None."""
        matches = _exact(self.cdgs(), name)
        return matches[0] if matches else None

    def update_cdg(self, cdg_id: int, payload: dict) -> dict:
        """PUT /credential-distribution-groups/{id}."""
        return self.put(f"/credential-distribution-groups/{cdg_id}", json=payload)

    @staticmethod
    def cdg_update_payload(cdg: dict, *, employee_groups: Sequence[dict] | None = None) -> dict:
        """Turn a CDG GET shape into the PUT body (``user_groups`` -> ``user_group_ids``, clamp
        ``restrict_number``).
        """
        restrict = cdg.get("restrict_number")
        try:
            restrict = min(int(restrict), CDG_MAX_RESTRICT_NUMBER)
        except (TypeError, ValueError):
            restrict = CDG_MAX_RESTRICT_NUMBER
        return {
            "name": cdg.get("name"),
            "enable_email_approval": cdg.get("enable_email_approval", False),
            "enable_user_limitation": cdg.get("enable_user_limitation", False),
            "employee_group_type": cdg.get("employee_group_type"),
            "employee_groups": list(
                cdg.get("employee_groups") or [] if employee_groups is None else employee_groups
            ),
            "restrict_number": restrict,
            "user_group_ids": [g["id"] for g in cdg.get("user_groups") or [] if "id" in g],
        }

    def cdg_add_users(self, cdg: dict | int, login_names: Sequence[str]) -> dict:
        """GET + PUT /credential-distribution-groups/{id} — add employees (login names) to a CDG."""
        current = self.cdg(cdg) if not isinstance(cdg, dict) else cdg
        existing = list(current.get("employee_groups") or [])
        known = {g.get("name") for g in existing}
        groups = existing + [{"name": n} for n in login_names if n not in known]
        payload = self.cdg_update_payload(current, employee_groups=groups)
        return self.update_cdg(current["id"], payload)

    # ------------------------------------------------------------------
    # clients / alerts / logs
    # ------------------------------------------------------------------
    def active_clients(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> list[dict]:
        """GET (paged) /clients/active — filters (``locationIds``, ``ssids``, ``views``...) pass
        through.
        """
        return self._list("/clients/active", dict(filters), limit=limit)

    def active_client_count(self, **filters: Any) -> int:
        """GET /clients/active/count."""
        body = self.get("/clients/active/count", **filters)
        if isinstance(body, dict):
            for key in ("count", "total_count", "total"):
                if isinstance(body.get(key), int):
                    return body[key]
        try:
            return int(body)
        except (TypeError, ValueError):
            return 0

    def client(self, client_id: int, **params: Any) -> dict:
        """GET /clients/{id}."""
        return self.get(f"/clients/{client_id}", **params)

    def client_by_mac(self, mac: str, **params: Any) -> dict:
        """GET /clients/byMac/{mac}."""
        return self.get(f"/clients/byMac/{mac}", **params)

    def alerts(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> list[dict]:
        """GET (paged) /alerts — ``startTime`` / ``endTime`` / ``severityIds`` etc. pass through."""
        return self._list("/alerts", dict(filters), limit=limit)

    def audit_logs(self, *, limit: int = DEFAULT_PAGE_SIZE, **filters: Any) -> list[dict]:
        """GET (paged) /logs/audit — requires ``startTime`` and ``endTime`` (epoch ms)."""
        return self._list("/logs/audit", dict(filters), limit=limit)


__all__ = ["XIQ", "XIQ_BASE_URL", "PLATFORM_ONE_BASE_URL"]
