# xiq-client

Unofficial Python client for the ExtremeCloud IQ API, including Extreme
Platform ONE. Not affiliated with Extreme Networks; the vendor package is
[`extremecloudiq-api`](https://pypi.org/project/extremecloudiq-api/).

It exists so that scripts like the ones in
[ExtremeNetworksSA](https://github.com/ExtremeNetworksSA) stop carrying
their own copy of login, retries, pagination, the "which VIQ?" menu, and
try/except blocks around every call.

- Token auth by default (`XIQ_API_TOKEN`), `POST /login` as fallback, or an
  interactive Email/Password prompt with `XIQ.from_prompt()`
- Timeouts on every request, retries with backoff, `Retry-After` on 429/503
- List methods fetch every page and return a `list`
- Long-running operations polled for you, with progress callbacks
- Typed errors that carry the API's own `error_message`
- Named helpers for the payloads scripts build by hand (end users, CCGs,
  CDGs, locations, onboarding, firewall objects)
- Works against Extreme Platform ONE with a `base_url` switch
- Editors autocomplete `xiq.` from the shipped type hints

## Install

```bash
pip install xiq-client
pip install "xiq-client[dotenv]"  # with .env support
```

For local development against this repo (needed for editor autocomplete):

```bash
pip install -e ".[dev,dotenv]"
```

## A complete script

```python
from xiq_client import XIQ
from xiq_client.cli import run


def main():
    xiq = XIQ.from_prompt(progress=True)   # env/.env token, else Email + Password
    xiq.choose_account()                   # numbered VIQ menu; no-op without external accounts

    for device in xiq.devices(connected=True, config_mismatch=True):
        print(device["hostname"], device.get("network_policy_name"))


if __name__ == "__main__":
    run(main)   # library errors print as "error: ..." and exit non-zero
```

That is the whole script. There is no login block, no VIQ picker, no
pagination loop, and no try/except: `run()` handles `CredentialsError`,
`AuthenticationError`, `APIError` and friends with a clean message and a
distinct exit code.

## Quickstart

```python
from xiq_client import XIQ

xiq = XIQ()                                   # token from XIQ_API_TOKEN

xiq.devices(connected=True)                   # list of dicts, every page
xiq.devices(hostnames=["ap-1", "ap-2"], fields=["ID", "HOSTNAME"])
xiq.devices_in_building("HQ", device_function="AP")
xiq.device_count(connected=False)             # one request, reads total_count

xiq.endusers(user_group_id=42)
xiq.create_enduser(42, name="Ann Lee", email="ann@example.com",
                   email_password_delivery="ann@example.com")
xiq.usergroup_id("Staff")                     # raises NotFoundError listing similar names

xiq.ccg_add_devices(xiq.ccg_id("Lab APs"), [101, 102])
xiq.assign_network_policy([101, 102], xiq.network_policy_id("Corp"))

result = xiq.send_cli([101], "show version", wait=True)
for device_id, outputs in XIQ.cli_outputs(result).items():
    print(device_id, outputs[0]["output"])

status = xiq.deploy_config([101, 102], wait=True)   # "SUCCEEDED"
```

`XIQ` is also a context manager, so a long-running script can release the
HTTP connection pool when it is done (the token is not revoked):

```python
with XIQ() as xiq:
    ...
```

Full method → endpoint table: [METHODS.md](METHODS.md) (generated from the
code, so it is always current).

## Credentials

Resolved in order:

1. Arguments — `XIQ(token="...")`, or `XIQ(username=..., password=...)`
   (`POST /login`). All constructor arguments are keyword-only.
2. Environment — `XIQ_API_TOKEN` (preferred), or `XIQ_USERNAME` /
   `XIQ_PASSWORD`. `XIQ_TOKEN` is still read if `XIQ_API_TOKEN` is empty.
   Optional `XIQ_BASE_URL` selects the API host.
3. A `.env` file in the current working directory (needs the `dotenv`
   extra; never overrides real environment variables).
4. `XIQ.from_prompt()` additionally asks for Email and Password on the
   terminal when none of the above is set, retrying on a bad login.

Two VIQs at once: `XIQ(token=src)` and `XIQ(token=dst)`, or
`other = xiq.for_account(viq_id)` to get a second client switched into an
external account while the first stays where it is.

### API tokens

- Recommended: create a Platform ONE key (`extr_sk_...`) under
  **Administration & Settings > Integrations**. It works with either
  supported endpoint.
- Alternatively, generate an XIQ token through `/login` (valid for 24
  hours) and `/auth/apitoken` (configurable expiration). It works only with
  the default `api.extremecloudiq.com` endpoint.
- Or set `XIQ_USERNAME` and `XIQ_PASSWORD`; the script obtains a new
  24-hour `/login` token each run.

## Extreme Platform ONE

Same paths, different base URL:

```python
from xiq_client import XIQ, PLATFORM_ONE_BASE_URL

xiq = XIQ(base_url=PLATFORM_ONE_BASE_URL)
```

Or set `XIQ_BASE_URL=https://cloudapi.extremecloudiq.com/xiq/v1`. A
Platform ONE key works with either endpoint; classic XIQ JWTs work only
with `https://api.extremecloudiq.com`, and the client logs a warning if
one is pointed at the Platform ONE host.

## Errors

```python
from xiq_client import (
    APIError, AuthenticationError, NotFoundError, DuplicateNameError,
    AmbiguousNameError, LROFailedError, LROTimeoutError, CredentialsError,
)

try:
    xiq.create_site({"name": "HQ", ...})
except DuplicateNameError:
    site = xiq.site_by_name("HQ")          # already there; carry on
except AuthenticationError:                # bad/expired token (401/403)
    ...
except APIError as e:
    print(e.status_code, e.error_message)  # the API's own message, if any
```

`str(e)` already includes the method, URL, status and the API's
`error_message`, so `print(e)` is usually enough. `NotFoundError` covers
HTTP 404 and by-name helpers that find nothing; `AmbiguousNameError` is
raised when a name matches more than one object. Both are `APIError`s, so
a plain `except APIError` still catches them. HTTP 403 is an
`AuthenticationError` (a valid token with missing scopes returns 403), so
do not use that catch to trigger a re-login.

### Retries

Connection failures and HTTP 429/502/503/504 are retried with backoff for
every method. Read timeouts and HTTP 500 are retried only for GET, because
a timed-out POST may already have been applied. Pass
`XIQ(retry_unsafe=True)` to retry those too.

## Progress and long-running operations

```python
xiq = XIQ(progress=True)          # "/devices: page 2 of 7", "LRO RUNNING (30s)" on stderr
xiq = XIQ(progress=logger.info)   # or any callable taking a string

state = xiq.wait_lro(url, interval=30, on_poll=lambda s, t: spinner())
state.status, state.response      # LROState

xiq.advanced_onboard(extreme=serials, wait=True, on_poll=show)   # success/failure lists
xiq.viq_export(wait=True).response["export_file_name"]
xiq.deploy_config(ids, wait=True, raise_on_failure=False)        # "SUCCEEDED" / "FAILED"
```

## Escape hatches

Anything without a named method goes through the same retry, timeout and
auth path:

```python
xiq.get("/alerts", order="DESC", limit=50)
xiq.post("/devices/:onboard", json=payload)
xiq.paged("/clients/active", {"ssids": "Guest"})   # iterator, every page
xiq.first_page("/devices", limit=1)["total_count"]
xiq.count("/devices", connected=True)
url = xiq.post_lro("/account/viq/export")
xiq.wait_lro(url)
```

`devices()` and the other list methods also pass unknown keyword arguments
through as raw query parameters (for example `deviceTypes="REAL"`).

## Migrating a script from a copied `xiq_api.py`

| Old (`from app.xiq_api import XIQ`)       | New (`from xiq_client import XIQ`)                     |
|-------------------------------------------|--------------------------------------------------------|
| token-or-prompt block + `XIQ(user_name=…)` | `XIQ.from_prompt()`                                   |
| `selectManagedAccount()` + 35-line menu   | `xiq.choose_account()`                                 |
| `if r != "Success": print; SystemExit`    | nothing; wrap `main` in `xiq_client.cli.run`           |
| `collectDevices(pageSize=100)`            | `xiq.devices()`                                        |
| `getFloorIds(name)`                       | `xiq.floor_ids_for_building(name)`                     |
| `DevicesFromBuilding(name)`               | `xiq.devices_in_building(name, device_function="AP")`  |
| `checkForCCG(name)` → `(bool, dict)`      | `xiq.ccg_by_name(name)` or `xiq.ccg_id(name)`          |
| `createCCG({...})["id"]`                  | `xiq.create_ccg(name, device_ids=ids)["id"]`           |
| `sendCLI(ids, cmds)` + LRO loop           | `xiq.send_cli(ids, cmds, wait=True)`                   |
| `advanceOnboardAPs(payload, lro=True)` + loop | `xiq.advanced_onboard(extreme=…, wait=True)`       |
| `check_lro_status(url)` → `(done, data)`  | `xiq.lro(url)` → `LROState`                            |
| `'duplicate' in response['error_message']` | `except DuplicateNameError`                           |
| hand-rolled pagination loops              | any list method, or `xiq.paged(path)`                  |

## Releasing

Push a `v*` tag (for example `v0.1.3`). The Publish workflow runs the
tests, checks that `METHODS.md` is current, builds, and uploads through
PyPI Trusted Publishing. Existing versions cannot be overwritten.
