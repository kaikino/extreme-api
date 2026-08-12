# xiq-client

Python client for the ExtremeCloud IQ API.

- Token auth by default (`XIQ_TOKEN`), `POST /login` as legacy fallback
- Timeouts on every request (connect 10 s / read 60 s)
- Retries with backoff; honors `Retry-After` on 429/503
- Automatic pagination — list methods return iterators
- Works against Extreme Platform ONE with a `base_url` switch

## Install

```bash
pip install xiq-client
pip install "xiq-client[dotenv]"  # with .env support
```

## Quickstart

```python
from xiq_client import XIQ

xiq = XIQ()  # token from the XIQ_TOKEN environment variable

for user in xiq.endusers(user_group_ids=42):
    print(user["user_name"])
```

Full method → endpoint table: [METHODS.md](METHODS.md).

## Credentials

Resolved in order:

1. Arguments — `XIQ(token="...")`, or `username=`/`password=` (legacy login).
2. Environment — `XIQ_TOKEN` (preferred), or `XIQ_USERNAME`/`XIQ_PASSWORD`.
3. A `.env` file, for local use. Needs the dotenv extra; never overrides real
   environment variables:

   ```bash
   pip install "xiq-client[dotenv]"
   cp .env.example .env   # then fill in XIQ_TOKEN
   ```

   `.env` is found from the current working directory, not the script's
   directory

Syncing between two VIQs? Pass tokens explicitly: `XIQ(token=src)`, `XIQ(token=dst)`.

## Extreme Platform ONE

The XIQ API is hosted unchanged on Platform ONE — same paths, different base URL:

```python
from xiq_client import XIQ, PLATFORM_ONE_BASE_URL

xiq = XIQ(token="...", base_url=PLATFORM_ONE_BASE_URL)
```

Tokens are **not** interchangeable between the platforms and are created
separately: XIQ tokens (JWTs) under XIQ → Administration → Integrations,
Platform ONE API keys (`extr_sk_...`) under Platform ONE → Administration &
Settings → Integrations. The client logs a warning if the token format doesn't
match the base URL it's pointed at.

## Errors

```python
from xiq_client import APIError, AuthenticationError, XIQError

try:
    xiq.get("/devices/999")
except AuthenticationError:      # bad/expired token (401/403)
    ...
except APIError as e:
    print(e.status_code, e.body) # 404, 429, ...; None = retries exhausted
```

## Coverage

Named methods cover accounts/VIQ (backup, export, import, download), devices (onboard, CLI, reboot, rename,
locations, policy assign), locations/sites/buildings/floors (incl. floorplan
upload), end users/PPSK/PCGs, network policies and deployments, SSIDs, CCGs,
radio profiles, firewall objects, admin users, CDGs, and audit logs. Payload
shapes come from the scripts themselves.

Anything else goes through the escape hatches, with the same
timeout/retry/auth behavior:

```python
xiq.get("/alerts", order="DESC")
xiq.paged("/clients/active")               # auto-paginated iterator
xiq.post_lro("/account/viq/export")        # returns the LRO Location URL
```

## Migrating a script from the copied `xiq_api.py`

| Old (`from app.xiq_api import XIQ`)             | New (`from xiq_client import XIQ`)          |
| ----------------------------------------------- | ------------------------------------------- |
| `XIQ(user_name=u, password=p)`                  | `XIQ()` + `XIQ_TOKEN` env var               |
| `xiq.collectDevices(pageSize=100)`              | `list(xiq.devices(limit=100))`              |
| `xiq.collectNetworkPolicies(pageSize)`          | `list(xiq.network_policies())`              |
| `xiq.changeNetworkPolicy(payload)`              | `xiq.assign_network_policy(payload)`        |
| `xiq.selectManagedAccount()` + `switchAccount`  | `xiq.external_accounts()` + `xiq.switch_account(viq_id)` |
| hand-rolled pagination loops                    | any `xiq.paged(path)` iterator              |
| pandas DataFrames from some methods             | plain `dict` / iterators                    |
