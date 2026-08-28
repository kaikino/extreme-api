# xiq-client

Unofficial Python client for the ExtremeCloud IQ API, including Extreme
Platform ONE. Not affiliated with Extreme Networks; the vendor package is
[`extremecloudiq-api`](https://pypi.org/project/extremecloudiq-api/).

- Token auth by default (`XIQ_API_TOKEN`; `XIQ_TOKEN` still works), `POST /login` as fallback
- Timeouts on every request (connect 10 s / read 60 s)
- Retries with backoff; honors `Retry-After` on 429/503
- Automatic pagination — list methods return iterators
- Works against Extreme Platform ONE with a `base_url` switch
- Typed public methods — editors autocomplete `xiq.` after the package is installed

## Install

```bash
pip install xiq-client
pip install "xiq-client[dotenv]"  # with .env support
```

For local development against this repo (needed for editor autocomplete):

```bash
pip install -e ".[dotenv]"
```

## Quickstart

```python
from xiq_client import XIQ

xiq = XIQ()  # token from the XIQ_API_TOKEN environment variable

for user in xiq.endusers(user_group_ids=42):
    print(user["user_name"])
```

Full method → endpoint table:
[METHODS.md](https://github.com/kaikino/xiq-client/blob/main/METHODS.md).

Typing `xiq.` in VS Code, Cursor, PyCharm, or similar lists every named
method (`devices`, `endusers`, `usergroups`, `get`, `paged`, …) from the
type hints shipped with the package.

## Credentials

Resolved in order:

1. Arguments — `XIQ(token="...")`, or `username=`/`password=` (`POST /login`).
2. Environment — `XIQ_API_TOKEN` (preferred), or `XIQ_USERNAME`/`XIQ_PASSWORD`.
   `XIQ_TOKEN` is still read if `XIQ_API_TOKEN` is empty.
   Optional `XIQ_BASE_URL` selects the API host.
3. A `.env` file, for local use. Needs the dotenv extra; never overrides real
   environment variables:

   ```bash
   pip install "xiq-client[dotenv]"
   cp .env.example .env   # then fill in XIQ_API_TOKEN
   ```

   `.env` is loaded from the current working directory only, not parent
   directories and not the script's directory.

Syncing between two VIQs? Pass tokens explicitly: `XIQ(token=src)`, `XIQ(token=dst)`.

### API tokens

- Recommended: create a Platform ONE key (`extr_sk_...`) under
**Administration & Settings > Integrations**. It works with either
supported endpoint.
- Alternatively, generate an XIQ token through `/login` (valid for 24
hours) and `/auth/apitoken` (configurable expiration) with
`usergroup:r` and `enduser` permissions. It works only with the
default `api.extremecloudiq.com` endpoint.
- Or set `XIQ_USERNAME` and `XIQ_PASSWORD`; the script obtains a new
24-hour `/login` token each run.

Set the selected key as `XIQ_API_TOKEN`.

## Extreme Platform ONE

The XIQ API is hosted on Platform ONE — same paths, different base URL:

```python
from xiq_client import XIQ, PLATFORM_ONE_BASE_URL

xiq = XIQ(base_url=PLATFORM_ONE_BASE_URL)
```

Or set `XIQ_BASE_URL=https://cloudapi.extremecloudiq.com/xiq/v1`.

A Platform ONE key (`extr_sk_...`) works with either endpoint. Classic XIQ
tokens from `/login` or `/auth/apitoken` work only with
`https://api.extremecloudiq.com`. The client logs a warning if a JWT is
pointed at the Platform ONE host.

## Errors

```python
from xiq_client import APIError, AuthenticationError, LROTimeoutError, XIQError

try:
    xiq.get("/devices/999")
except AuthenticationError:      # bad/expired token (401/403)
    ...
except LROTimeoutError:
    ...
except APIError as e:
    print(e.status_code, e.body) # 404, 429, ...; None = retries exhausted
```

HTTP 403 is still raised as `AuthenticationError` in 0.1.x (a valid token with
missing scopes returns 403). Do not use that catch to trigger a re-login.

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
url = xiq.post_lro("/account/viq/export")  # Location URL of a long-running op
xiq.wait_lro(url)                          # poll until done or timeout
```

## Migrating a script from the copied `xiq_api.py`

| Old (`from app.xiq_api import XIQ`)             | New (`from xiq_client import XIQ`)          |
| ----------------------------------------------- | ------------------------------------------- |
| `XIQ(user_name=u, password=p)`                  | `XIQ()` + `XIQ_API_TOKEN` env var           |
| `xiq.collectDevices(pageSize=100)`              | `list(xiq.devices(limit=100))`              |
| `xiq.collectNetworkPolicies(pageSize)`          | `list(xiq.network_policies())`              |
| `xiq.changeNetworkPolicy(payload)`              | `xiq.assign_network_policy(payload)`        |
| `xiq.selectManagedAccount()` + `switchAccount`  | `xiq.external_accounts()` + `xiq.switch_account(viq_id)` |
| hand-rolled pagination loops                    | any `xiq.paged(path)` iterator              |
| pandas DataFrames from some methods             | plain `dict` / iterators                    |

## Releasing

Push a `v*` tag (for example `v0.1.1`) after adding this GitHub repository as a
[PyPI Trusted Publisher](https://docs.pypi.org/trusted-publishers/). Existing
versions cannot be overwritten.
