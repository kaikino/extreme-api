# Method reference

Generated from the `XIQ` class by `tools/gen_methods.py`; do not edit by hand.

Every public method, the API call behind it, and what it returns. Paths are
relative to the base URL (`https://api.extremecloudiq.com`, or the Platform
ONE equivalent). "(paged)" methods fetch every page and return a `list`.

Anything not listed is still reachable with the same retry/timeout/auth
behavior via `xiq.get/post/put/delete(path, ...)`, `xiq.paged(path, params)`,
`xiq.first_page(...)`, `xiq.count(...)`, and `xiq.post_lro(path)` +
`xiq.wait_lro(url)`.


## Core (works for any endpoint)

| Method | API call | Notes |
|---|---|---|
| `get(path, **params)` | GET ``path`` | Query string from keyword arguments |
| `post(path, json=…, **params)` | POST ``path`` with an optional JSON body | Query string from kwargs |
| `put(path, json=…, **params)` | PUT ``path`` with an optional JSON body | Query string from kwargs |
| `delete(path, json=…, **params)` | DELETE ``path`` | Optional JSON body; query string from kwargs |
| `first_page(path, params=…, page=…, limit=…)` | GET one page of a list endpoint; returns the raw page dict |  |
| `count(path, **params)` |  | Total number of items a list endpoint would return (one request) |
| `paged(path, params=…, limit=…, on_page=…)` |  | Iterate every item of a paginated list endpoint |
| `post_lro(path, json=…, params=…, files=…)` | POST a long-running operation; returns the Location URL to poll |  |
| `check_lro(url)` | GET a long-running operation's Location URL once (raw body) |  |
| `lro(url)` | GET a long-running operation's Location URL once, decoded |  |
| `wait_lro(url, timeout=…, interval=…, initial_delay=…, on_poll=…, raise_on_failure=…)` |  | Poll an LRO URL until it finishes or ``timeout`` seconds elapse |
| `token` |  | The bearer token currently in use (after login or account switch) |
| `logout()` | POST /logout | revoke the current token |
| `close()` |  | Close the underlying HTTP session. The token is not revoked |

## Construction & account context

| Method | API call | Notes |
|---|---|---|
| `from_prompt(token=…, attempts=…, input_fn=…, getpass_fn=…, print_fn=…, **kwargs)` |  | Build a client from the environment, else prompt for Email/Password |
| `choose_account(accounts=…, home=…, input_fn=…, print_fn=…, title=…)` |  | Interactive VIQ picker; switches into the choice and returns its name |
| `for_account(viq_id, viq_name=…)` |  | A new client switched into ``viq_id``; this client stays on its VIQ |
| `select_managed_account()` | GET /account/home + GET /account/external | ``(accounts, home_viq_name)`` |
| `switch_account(viq_id, viq_name=…)` | POST /account/:switch | switch into an external VIQ; returns its name |
| `account_home()` | GET /account/home | the current VIQ (also sets ``viq_name`` / ``viq_id``) |
| `external_accounts()` | GET /account/external | VIQs this admin can switch into (``[]`` if none) |
| `generate_api_token(permissions, expire_time=…, description=…)` | POST /auth/apitoken | create a long-lived API token |
| `token_info()` | GET /auth/apitoken/info | metadata for the current token |
| `viq_info()` | GET /account/viq |  |
| `viq_backup()` | POST /account/viq/:backup |  |
| `viq_export(wait=…, timeout=…, interval=…, on_poll=…)` | POST (LRO) /account/viq/export | start a VIQ export |
| `viq_download(report_name)` | GET (bytes) /account/viq/download?reportName= |  |
| `viq_import(file, filename=…, resend_user_notifications=…, wait=…, timeout=…, interval=…, on_poll=…)` | POST (LRO, multipart) /account/viq/import | import a VIQ backup |

## Devices

| Method | API call | Notes |
|---|---|---|
| `devices(views=…, fields=…, location_id=…, location_ids=…, hostnames=…, mac_addresses=…, serials=…, connected=…, config_mismatch=…, admin_states=…, device_types=…, null_field=…, device_function=…, order=…, sort_field=…, limit=…, **filters)` | GET (paged) /devices | every device matching the filters |
| `device_count(**filters)` | GET /devices?limit=1 | total device count for the filters (one request) |
| `device(device_id, **params)` | GET /devices/{id} | extra query params (e.g. ``fields="CONNECTED"``) pass through |
| `device_by_serial(serial)` | GET /devices?sns= | the device with this serial number, or None |
| `device_by_hostname(hostname)` | GET /devices?hostnames= | the device with exactly this hostname, or None |
| `delete_device(device_id)` | DELETE /devices/{id} |  |
| `delete_devices(device_ids)` | POST /devices/:delete |  |
| `unmanage_devices(device_ids)` | POST /devices/:unmanage |  |
| `onboard_devices(payload)` | POST /devices/:onboard |  |
| `advanced_onboard(payload=…, extreme=…, exos=…, voss=…, unmanaged=…, wait=…, timeout=…, interval=…, on_poll=…)` | POST (LRO) /devices/:advanced-onboard | onboard by serial number |
| `reboot_device(device_id)` | POST /devices/{id}/:reboot |  |
| `wait_for_device_connected(device_id, timeout=…, interval=…, on_poll=…)` | GET /devices/{id}?fields=CONNECTED until connected or ``timeout``; returns the final state |  |
| `send_cli(device_ids, commands, wait=…, timeout=…, interval=…, initial_delay=…, on_poll=…)` | POST /devices/:cli | run CLI commands on devices |
| `cli_outputs(result)` |  | Flatten a :meth:`send_cli` result to ``{device_id (int): [outputs...]}`` |
| `set_hostname(device_id, hostname)` | PUT /devices/{id}/hostname?hostname= | the new name goes in the query string |
| `set_description(device_id, description)` | PUT (raw body) /devices/{id}/description | the body is the bare string |
| `device_location(device_id)` | GET /devices/{id}/location |  |
| `set_device_location(device_id, payload, x=…, y=…, latitude=…, longitude=…)` | PUT /devices/{id}/location | ``payload`` may be a dict or a floor/location id |
| `move_device(device_id, location_id, x=…, y=…)` | GET + PUT /devices/{id}/location | move a device, keeping its x/y unless given |
| `assign_location(devices, location_id=…, x=…, y=…, latitude=…, longitude=…)` | POST /devices/location/:assign | ``devices`` is a payload dict or a list of ids |
| `device_network_policy(device_id)` | GET /devices/{id}/network-policy |  |
| `set_device_network_policy(device_id, payload=…, network_policy_id=…)` | PUT /devices/{id}/network-policy?networkPolicyId= | ``payload`` may be the id or a dict |
| `assign_network_policy(devices, network_policy_id=…)` | POST /devices/network-policy/:assign | ``devices`` is a list of ids, a dict, or a JSON string |
| `device_alarms(device_id, limit=…, **filters)` | GET (paged) /devices/{id}/alarms | pass ``startTime`` / ``endTime`` (epoch ms) |
| `device_alarm_count(device_id, **filters)` | GET /devices/{id}/alarms?limit=1 | alarm count in one request |
| `wifi_interfaces(device_id, **params)` | GET /devices/{id}/interfaces/wifi | optional ``startTime`` / ``endTime``; returns the list |
| `radio_information(device_ids=…, include_disabled_radio=…, limit=…, **filters)` | GET (paged) /devices/radio-information | ``device_ids`` is chunked to the API's 50-id limit |

## Locations

| Method | API call | Notes |
|---|---|---|
| `locations_tree(expand_children=…, parent_id=…)` | GET /locations/tree | pass ``parent_id`` to list children of a site/building |
| `locations_flat()` | GET /locations/tree (walked) | every location as ``{id, name, type, parent_id, path}`` |
| `init_location(organization, country)` | POST /locations/:init |  |
| `create_location(payload, parent_id=…)` | POST /locations | ``payload`` may be a dict or a name (with ``parent_id``) |
| `sites(limit=…, **filters)` | GET (paged) /locations/site | filters (``name``, ``ids``, ``order``) pass through |
| `site_by_name(name)` | GET /locations/site?name= | the site with exactly this name, or None |
| `site_id(name)` | GET /locations/site?name= | the id of the uniquely named site (raises if 0 or >1) |
| `create_site(payload)` | POST /locations/site |  |
| `update_site(site, payload=…, **changes)` | PUT /locations/site/{id} | pass the GET shape (read-only keys are stripped) plus changes |
| `buildings(limit=…, **filters)` | GET (paged) /locations/building | filters (``name``, ``ids``, ``order``) pass through |
| `building_by_name(name)` | GET /locations/building?name= | the building with exactly this name, or None if 0 or >1 |
| `building_id(name)` | GET /locations/building?name= | the id of the uniquely named building (raises if 0 or >1) |
| `create_building(payload)` | POST /locations/building |  |
| `floors(limit=…, **filters)` | GET (paged) /locations/floor |  |
| `floors_for_building(building)` | GET /locations/building?name= + GET /locations/tree?parentId= | floors of a building |
| `floor_ids_for_building(building)` |  | Floor ids of a building (see :meth:`floors_for_building`) |
| `floor_in_building(building, floor_name)` |  | The floor named ``floor_name`` in a building (exact, then case-insensitive match) |
| `floor_ids_for_site(site)` | GET /locations/tree walked from a site | every floor id under it |
| `devices_in_site(site, **filters)` |  | Devices on any floor of a site (see :meth:`devices` for filters) |
| `devices_in_building(building, **filters)` |  | Devices on any floor of a building (see :meth:`devices` for filters) |
| `devices_in_floor(building, floor_name, **filters)` |  | Devices on one floor of a building (see :meth:`devices` for filters) |
| `create_floor(payload)` | POST /locations/floor |  |
| `upload_floorplan(file, filename=…, content_type=…)` | POST (multipart) /locations/floorplan | ``file`` may be a path or an open binary file |
| `countries()` | GET /countries | the list of country codes |
| `validate_country(country_code)` | GET /countries/{code}/:validate | True when the code is valid |

## End users (PPSK) / user groups / PCGs

| Method | API call | Notes |
|---|---|---|
| `endusers(user_group_id=…, user_group_ids=…, usernames=…, limit=…, **filters)` | GET (paged) /endusers | PPSK users, optionally by group / user name |
| `enduser(enduser_id)` | GET /endusers/{id} |  |
| `enduser_by_username(user_name, user_group_id=…)` | GET /endusers?usernames= | the PPSK user with exactly this user name, or None |
| `create_enduser(payload, name=…, user_name=…, password=…, email=…, phone=…, organization=…, visit_purpose=…, description=…, email_password_delivery=…, sms_password_delivery=…, **extra)` | POST /endusers | ``payload`` is a dict, or the user group id with keyword fields |
| `update_enduser(enduser_id, payload)` | PUT /endusers/{id} |  |
| `set_enduser_password(enduser_id, password)` | PUT /endusers/{id} with ``{"password": ...}``; verifies the echoed password |  |
| `delete_enduser(enduser_id)` | DELETE /endusers/{id} |  |
| `usergroups(limit=…, **filters)` | GET (paged) /usergroups |  |
| `usergroup_by_name(name)` | GET /usergroups | the user group with exactly this name, or None |
| `usergroup_id(name)` | GET /usergroups | the id of the uniquely named user group (raises if 0 or >1) |
| `pcg_users(policy_id, limit=…)` | GET (paged) /pcgs/key-based/network-policy-{id}/users |  |
| `add_pcg_users(policy_id, users)` | POST /pcgs/key-based/network-policy-{id}/users | ``users`` are ``{name, email, user_group_name}`` dicts |
| `add_pcg_user(policy_id, name, email, user_group_name)` | POST /pcgs/key-based/network-policy-{id}/users | add one user |
| `delete_pcg_users(policy_id, user_ids)` | DELETE /pcgs/key-based/network-policy-{id}/users | DELETE with a JSON body; the API answers 202 |
| `delete_pcg_user(policy_id, user_id)` | DELETE /pcgs/key-based/network-policy-{id}/users | remove one user |

## Network policies / deployments / SSIDs

| Method | API call | Notes |
|---|---|---|
| `network_policies(limit=…, **filters)` | GET (paged) /network-policies | filters (``policyNames``, ``keyword``) pass through |
| `network_policy_by_name(name)` | GET /network-policies?policyNames= | the policy with exactly this name, or None |
| `network_policy_id(name)` | GET /network-policies?policyNames= | the id of the uniquely named policy (raises if 0 or >1) |
| `deploy_config(device_ids, complete_update=…, activate_at_next_reboot=…, activation_delay_seconds=…, wait=…, timeout=…, interval=…, on_poll=…, raise_on_failure=…)` | POST (LRO) /deployments | push config to devices |
| `ssids(limit=…, **filters)` | GET (paged) /ssids |  |
| `ssid_by_name(name)` | GET /ssids | the SSID with exactly this name, or None |
| `set_psk_password(ssid_id, password)` | PUT (raw body) /ssids/{id}/psk/password | the body is the bare string |

## CCGs (cloud config groups)

| Method | API call | Notes |
|---|---|---|
| `ccgs(limit=…, **filters)` | GET (paged) /ccgs |  |
| `ccg(ccg_id)` | GET /ccgs/{id} |  |
| `ccg_by_name(name)` | GET /ccgs | the CCG with exactly this name, or None |
| `ccg_id(name)` | GET /ccgs | the id of the uniquely named CCG (raises if 0 or >1) |
| `create_ccg(payload, description=…, device_ids=…)` | POST /ccgs | ``payload`` is a dict, or the name with ``description`` / ``device_ids`` |
| `update_ccg(ccg_id, payload)` | PUT /ccgs/{id} | ``payload`` is ``{name, description, device_ids}`` |
| `set_ccg_devices(ccg_id, device_ids)` | GET + PUT /ccgs/{id} | replace the CCG's device list |
| `ccg_add_devices(ccg_id, device_ids)` | GET + PUT /ccgs/{id} | add devices to the CCG (keeps existing members) |
| `ccg_remove_devices(ccg_id, device_ids)` | GET + PUT /ccgs/{id} | remove devices from the CCG |
| `delete_ccg(ccg_id)` | DELETE /ccgs/{id} |  |

## Radio profiles

| Method | API call | Notes |
|---|---|---|
| `radio_profiles(limit=…, **filters)` | GET (paged) /radio-profiles |  |
| `radio_profile(profile_id)` | GET /radio-profiles/{id} |  |
| `radio_profile_by_name(name)` | GET /radio-profiles | the profile with exactly this name, or None |
| `radio_usage_opt(profile_id)` | GET /radio-profiles/radio-usage-opt/{id} |  |
| `channel_selection(profile_id)` | GET /radio-profiles/channel-selection/{id} |  |
| `radio_profile_details(profile)` |  | Radio profile merged with its ``channel_selection`` and ``radio_usage_opt`` sub-objects |

## Firewall / network objects

| Method | API call | Notes |
|---|---|---|
| `ip_firewall_policies(limit=…, **filters)` | GET (paged) /ip-firewall-policies |  |
| `create_ip_firewall_policy(payload, description=…, rules=…)` | POST /ip-firewall-policies | ``payload`` is a dict, or the name with ``rules`` |
| `update_ip_firewall_policy(policy_id, payload)` | PUT /ip-firewall-policies/{id} |  |
| `delete_ip_firewall_policy(policy_id)` | DELETE /ip-firewall-policies/{id} |  |
| `l3_address_profiles(address_type=…, limit=…, **filters)` | GET (paged) /l3-address-profiles | ``address_type`` is IP_ADDRESS / HOST_NAME / IP_SUBNET / IP_RANGE |
| `create_l3_address_profile(payload, address_type=…, value=…, netmask=…, description=…, **extra)` | POST /l3-address-profiles | returns the created profile (unwrapped from ``*_address_profile``) |
| `network_services(limit=…, **filters)` | GET (paged) /network-services | filters (``name``, ``ipProtocol``) pass through |
| `network_service_by_name(name)` | GET /network-services?name= | the service with exactly this name, or None |

## Admin users / credential distribution groups

| Method | API call | Notes |
|---|---|---|
| `users(limit=…, **filters)` | GET (paged) /users | admin accounts |
| `user(user_id)` | GET /users/{id} |  |
| `user_by_login(login_name)` | GET /users | the admin with exactly this login name, or None |
| `create_user(payload)` | POST /users |  |
| `create_admin_user(login_name, display_name, role=…, idle_timeout=…, location_ids=…, access_scope=…, viq_access_control=…, **extra)` | POST /users | create an admin account by keyword |
| `external_users(limit=…, **filters)` | GET (paged) /users/external | SSO / external admin accounts |
| `create_external_user(payload, user_role=…, org_id=…, location_ids=…, **extra)` | POST /users/external | ``payload`` is a dict, or the login name with ``user_role`` |
| `cdgs(limit=…, **filters)` | GET (paged) /credential-distribution-groups |  |
| `cdg(cdg_id)` | GET /credential-distribution-groups/{id} |  |
| `cdg_by_name(name)` | GET /credential-distribution-groups | the CDG with exactly this name, or None |
| `update_cdg(cdg_id, payload)` | PUT /credential-distribution-groups/{id} |  |
| `cdg_update_payload(cdg, employee_groups=…)` |  | Turn a CDG GET shape into the PUT body (``user_groups`` -> ``user_group_ids``, clamp ``restrict_number``) |
| `cdg_add_users(cdg, login_names)` | GET + PUT /credential-distribution-groups/{id} | add employees (login names) to a CDG |

## Clients / alerts / logs

| Method | API call | Notes |
|---|---|---|
| `active_clients(limit=…, **filters)` | GET (paged) /clients/active | filters (``locationIds``, ``ssids``, ``views``...) pass through |
| `active_client_count(**filters)` | GET /clients/active/count |  |
| `client(client_id, **params)` | GET /clients/{id} |  |
| `client_by_mac(mac, **params)` | GET /clients/byMac/{mac} |  |
| `alerts(limit=…, **filters)` | GET (paged) /alerts | ``startTime`` / ``endTime`` / ``severityIds`` etc. pass through |
| `audit_logs(limit=…, **filters)` | GET (paged) /logs/audit | requires ``startTime`` and ``endTime`` (epoch ms) |
