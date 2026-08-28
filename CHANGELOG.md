# Changelog

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
