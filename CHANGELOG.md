# Changelog

## 0.1.3

Built from a review of 36 ExtremeNetworksSA scripts migrated onto 0.1.2.
The copied `xiq_api.py` modules were gone, but the scripts themselves had
not gotten shorter: every one still carried a login prompt, a VIQ picker,
try/except-print-exit around each call, and hand-built payloads. 0.1.3
moves those into the library.

The package is pre-1.0, so the breaking changes below ship in a patch
release. Pin `xiq-client==0.1.2` if a script depends on the old shapes.

### Breaking changes

- `XIQ(...)` arguments are keyword-only. `XIQ("user", "pw")` used to send
  the email as a bearer token; it now raises `TypeError`.
- List methods (`devices()`, `endusers()`, `ccgs()`, ...) return a `list`
  instead of an iterator. `xiq.paged(path)` is still the iterator.
- `wait_lro()` returns an `LROState` (`done`, `status`, `response`,
  `error`, `body`) instead of the raw body, and raises `LROFailedError`
  (an `APIError`) on failure.
- `devices()` sends no `views` when `fields=` is given; `views="FULL"`
  stays the default otherwise. Pass `views=None` to send neither.
- `send_cli(wait=True)` polls every 15 s after a 5 s initial delay
  (was every 2 s). Both are arguments now.
- `select_managed_account()` returns `([], home_name)` when there are no
  external accounts or the call is not permitted; it no longer raises.
- HTTP 404 raises `NotFoundError` (an `APIError`). By-name lookups raise
  `NotFoundError` or `AmbiguousNameError`, both `APIError` subclasses.
- Retries: read timeouts and HTTP 500 are retried only for GET unless
  `XIQ(retry_unsafe=True)`. A timed-out POST may already have been applied.
- `floors_for_building()` matches the building name exactly and raises
  `NotFoundError` (listing similar names) or `AmbiguousNameError`. It also
  accepts a building id.
- `wifi_interfaces()` and `countries()` return the list, unwrapping `data`.
- `validate_country()` returns a `bool`.

### Added

- `XIQ.from_prompt()` — token / env / `.env`, else an Email + Password
  prompt with retries.
- `xiq.choose_account()` — the numbered "which VIQ?" menu, switching into
  the choice; a no-op without external accounts.
- `xiq_client.cli.run(main)` — prints library errors cleanly and maps them
  to exit codes; `yes_no()` prompt helper.
- `XIQ(progress=True)` (or a callable) reports "page N of M" and LRO polls.
  `paged(on_page=)` and `wait_lro(on_poll=)` for finer control.
- `xiq.token` property, `xiq.for_account(viq_id)` returning a switched
  clone, and pickle support for `multiprocessing`.
- `APIError.error_message` / `.error_code`, included in `str(e)`;
  `DuplicateNameError`, `NotFoundError`, `AmbiguousNameError`,
  `LROFailedError`.
- `count(path)`, `first_page(path)`, `device_count()`, `device_alarm_count()`
  read `total_count` in one request.
- `lro(url)` and `lro_state(body)`; `wait_lro(initial_delay=,
  raise_on_failure=)`; `viq_export(wait=True)`, `viq_import(wait=True)`.
- `deploy_config(raise_on_failure=False)` returns `FAILED` instead of
  raising.
- Devices: typed `admin_states`, `device_types`, `fields`, `null_field`,
  `order`, `sort_field` filters and a client-side `device_function` filter;
  `device_by_serial()`, `device_by_hostname()`, `cli_outputs()`,
  `wait_for_device_connected()`, `move_device()`,
  `assign_location(ids, location_id)`, `assign_network_policy(ids, policy_id)`,
  `advanced_onboard(extreme=, exos=, voss=, wait=True)`,
  `radio_information(device_ids=)` chunked to 50 ids.
- Locations: `locations_flat()`, `site_id()`, `building_id()`,
  `floor_ids_for_building()`, `floor_ids_for_site()`, `floor_in_building()`,
  `devices_in_site()`, `devices_in_building()`, `devices_in_floor()`,
  `update_site(site_dict, **changes)` stripping read-only keys,
  `create_location(name, parent_id=)`, `upload_floorplan(path)`.
- End users: `endusers(user_group_id=, usernames=)`, `enduser()`,
  `enduser_by_username()`, `create_enduser(group_id, name=, email=, ...)`,
  `set_enduser_password()` verifying the echo, `usergroup_id()`,
  `add_pcg_user()`, `delete_pcg_user()`.
- Policies / SSIDs: `network_policy_id()`, `ssids()`, `ssid_by_name()`.
- CCGs: `ccg()`, `ccg_id()`, `create_ccg(name, device_ids=)`,
  `set_ccg_devices()`, `ccg_add_devices()`, `ccg_remove_devices()`.
- Radio profiles: `radio_profile()`, `radio_profile_by_name()`,
  `radio_profile_details()`.
- Firewall: `create_ip_firewall_policy(name, rules=)`,
  `l3_address_profiles(address_type=)`,
  `create_l3_address_profile(name, address_type=, value=, netmask=)`
  returning the unwrapped profile, `network_service_by_name()`.
- Admin: `user_by_login()`, `create_admin_user()`,
  `create_external_user(login, role)`, `cdg()`, `cdg_by_name()`,
  `cdg_update_payload()`, `cdg_add_users()`.
- Clients / alerts: `active_clients()`, `active_client_count()`,
  `client()`, `client_by_mac()`, `alerts()`.
- `XIQ` is a context manager (`with XIQ() as xiq:`) and has `close()`,
  which closes the HTTP session without revoking the token.
- Boolean query parameters are sent as `true` / `false` instead of
  Python's `True` / `False`.
- `METHODS.md` is generated from the code (`tools/gen_methods.py`) and
  checked in CI.

## 0.1.2

- Document `XIQ_API_TOKEN` as the preferred env var; `XIQ_TOKEN` is still accepted
- Platform ONE keys (`extr_sk_...`) work with either API host; classic XIQ JWTs do not
- Add `wait_lro()` to poll long-running operations until they finish
- `check_lro()` remains a single GET (the 0.1.1 docs said it waited; it did not)
- Send `User-Agent: xiq-client/<version>` on client-owned sessions
- Load `.env` only from the current working directory
- Add mocked tests and run them in CI
- Publish tagged releases (`v*`) to PyPI via Trusted Publishing
- `XIQ(user_name=…)` alias, `select_managed_account()`, `switch_account()`, `floors_for_building()`, `usergroup_by_name()`, `ccg_by_name()`
- `devices()` accepts list filters (`hostnames`, `location_ids`, `serials`, `connected`, `config_mismatch`) as repeated query params
- `send_cli(wait=True)` polls the CLI LRO (20 minute default timeout)
- `deploy_config(wait=True)` returns the LRO status string; `wait=False` returns the Location URL
- `assign_network_policy()` accepts a dict or a JSON string
- `viq_import()` accepts a filesystem path
- `AuthenticationError` is an `APIError` and carries `status_code`
- `device_alarms()` accepts `startTime` / `endTime`; add `site_by_name()`, `building_by_name()`, `network_policy_by_name()`
- `set_device_network_policy()` sends `networkPolicyId` as a query parameter

## 0.1.1

- Warn when a classic XIQ JWT is pointed at the Platform ONE host

## 0.1.0

- Initial release
