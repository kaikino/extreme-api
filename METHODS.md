# Method reference

Every named method and the XIQ API call behind it. Paths are relative to the
base URL (`https://api.extremecloudiq.com`, or the Platform ONE equivalent).

Anything not listed is still reachable with the same retry/timeout/auth
behavior via `xiq.get/post/put/delete(path, ...)`, `xiq.paged(path, params)`,
and `xiq.post_lro(path)` + `xiq.check_lro(url)`.

## Core (works for any endpoint)

| Method | API call | Notes |
|---|---|---|
| `get(path, **params)` | `GET <any path>` | query params as kwargs |
| `post(path, json=None, **params)` | `POST <any path>` |  |
| `put(path, json=None, **params)` | `PUT <any path>` |  |
| `delete(path, **params)` | `DELETE <any path>` |  |
| `paged(path, params=None, limit=100)` | `GET <any list path>` | iterator over every page |
| `post_lro(path, ...)` | `POST <any path>` | returns the Location URL of a long-running op |
| `check_lro(url)` | `GET <absolute LRO URL>` | poll until metadata.status is terminal |
| `logout()` | `POST /logout` | revokes the current token |

## Auth & tokens

| Method | API call | Notes |
|---|---|---|
| `generate_api_token(permissions, expire_time=…, description=…)` | `POST /auth/apitoken` | use this to stop hardcoding passwords |
| `token_info()` | `GET /auth/apitoken/info` |  |

## Account / VIQ context

| Method | API call | Notes |
|---|---|---|
| `account_home()` | `GET /account/home` |  |
| `external_accounts()` | `GET /account/external` |  |
| `switch_account(viq_id)` | `POST /account/:switch` | refreshes the bearer token from the response |
| `viq_info()` | `GET /account/viq` |  |
| `viq_backup()` | `POST /account/viq/:backup` |  |
| `viq_export()` | `POST (LRO) /account/viq/export` | returns the LRO Location URL — poll with check_lro() |
| `viq_download(report_name)` | `GET (bytes) /account/viq/download` | returns raw bytes |
| `viq_import(file, filename, resend_user_notifications=…)` | `POST (LRO) /account/viq/import` | multipart upload; returns the LRO Location URL |

## Devices

| Method | API call | Notes |
|---|---|---|
| `devices(views=…, location_id=…, limit=…)` | `GET (paged) /devices` | views=FULL default; location_id= and extra filters supported |
| `device(device_id)` | `GET /devices/{device_id}` |  |
| `delete_device(device_id)` | `DELETE /devices/{device_id}` |  |
| `delete_devices(device_ids)` | `POST /devices/:delete` |  |
| `unmanage_devices(device_ids)` | `POST /devices/:unmanage` |  |
| `onboard_devices(payload)` | `POST /devices/:onboard` |  |
| `advanced_onboard(payload, wait=…)` | `POST (LRO) /devices/:advanced-onboard` | wait=False returns the LRO Location URL |
| `reboot_device(device_id)` | `POST /devices/{device_id}/:reboot` |  |
| `send_cli(device_ids, commands)` | `POST /devices/:cli` | sends ?async=false |
| `set_hostname(device_id, hostname)` | `PUT /devices/{device_id}/hostname` | new name goes in the query string, no body |
| `set_description(device_id, description)` | `PUT (raw body) /devices/{device_id}/description` | body is the bare string, not JSON |
| `device_location(device_id)` | `GET /devices/{device_id}/location` |  |
| `set_device_location(device_id, payload)` | `PUT /devices/{device_id}/location` |  |
| `assign_location(payload)` | `POST /devices/location/:assign` |  |
| `device_network_policy(device_id)` | `GET /devices/{device_id}/network-policy` |  |
| `set_device_network_policy(device_id, payload)` | `PUT /devices/{device_id}/network-policy` |  |
| `assign_network_policy(payload)` | `POST /devices/network-policy/:assign` |  |
| `device_alarms(device_id, limit=…)` | `GET (paged) /devices/{device_id}/alarms` |  |
| `wifi_interfaces(device_id)` | `GET /devices/{device_id}/interfaces/wifi` |  |
| `radio_information(limit=…)` | `GET (paged) /devices/radio-information` |  |

## Locations

| Method | API call | Notes |
|---|---|---|
| `locations_tree(expand_children=…)` | `GET /locations/tree` |  |
| `init_location(organization, country)` | `POST /locations/:init` |  |
| `create_location(payload)` | `POST /locations` |  |
| `sites(limit=…)` | `GET (paged) /locations/site` |  |
| `create_site(payload)` | `POST /locations/site` |  |
| `update_site(site_id, payload)` | `PUT /locations/site/{site_id}` |  |
| `buildings(limit=…)` | `GET (paged) /locations/building` |  |
| `create_building(payload)` | `POST /locations/building` |  |
| `floors(limit=…)` | `GET (paged) /locations/floor` |  |
| `create_floor(payload)` | `POST /locations/floor` |  |
| `upload_floorplan(file, filename, content_type=…)` | `POST (multipart) /locations/floorplan` | multipart upload |
| `countries()` | `GET /countries` |  |
| `validate_country(country_code)` | `GET /countries/{country_code}/:validate` |  |

## End users (PPSK) / user groups / PCGs

| Method | API call | Notes |
|---|---|---|
| `endusers(limit=…)` | `GET (paged) /endusers` | filters pass through, e.g. user_group_ids= |
| `create_enduser(payload)` | `POST /endusers` |  |
| `update_enduser(enduser_id, payload)` | `PUT /endusers/{enduser_id}` |  |
| `delete_enduser(enduser_id)` | `DELETE /endusers/{enduser_id}` |  |
| `usergroups(limit=…)` | `GET (paged) /usergroups` |  |
| `pcg_users(policy_id, limit=…)` | `GET (paged) /pcgs/key-based/network-policy-{policy_id}/users` |  |
| `add_pcg_users(policy_id, users)` | `POST /pcgs/key-based/network-policy-{policy_id}/users` |  |
| `delete_pcg_users(policy_id, user_ids)` | `DELETE /pcgs/key-based/network-policy-{policy_id}/users` | DELETE with JSON body; API answers 202 |

## Network policies / deployments / SSIDs

| Method | API call | Notes |
|---|---|---|
| `network_policies(limit=…)` | `GET (paged) /network-policies` |  |
| `deploy_config(device_ids, complete_update=…, activate_at_next_reboot=…, activation_delay_seconds=…)` | `POST /deployments` | sends ?async=true with the delta-update policy payload |
| `set_psk_password(ssid_id, password)` | `PUT (raw body) /ssids/{ssid_id}/psk/password` | body is the bare string, not JSON |

## CCGs (cloud config groups)

| Method | API call | Notes |
|---|---|---|
| `ccgs(limit=…)` | `GET (paged) /ccgs` |  |
| `create_ccg(payload)` | `POST /ccgs` |  |
| `update_ccg(ccg_id, payload)` | `PUT /ccgs/{ccg_id}` |  |
| `delete_ccg(ccg_id)` | `DELETE /ccgs/{ccg_id}` |  |

## Radio profiles

| Method | API call | Notes |
|---|---|---|
| `radio_profiles(limit=…)` | `GET (paged) /radio-profiles` |  |
| `radio_usage_opt(profile_id)` | `GET /radio-profiles/radio-usage-opt/{profile_id}` |  |
| `channel_selection(profile_id)` | `GET /radio-profiles/channel-selection/{profile_id}` |  |

## Firewall / network objects

| Method | API call | Notes |
|---|---|---|
| `ip_firewall_policies(limit=…)` | `GET (paged) /ip-firewall-policies` |  |
| `create_ip_firewall_policy(payload)` | `POST /ip-firewall-policies` |  |
| `update_ip_firewall_policy(policy_id, payload)` | `PUT /ip-firewall-policies/{policy_id}` |  |
| `delete_ip_firewall_policy(policy_id)` | `DELETE /ip-firewall-policies/{policy_id}` |  |
| `l3_address_profiles(limit=…)` | `GET (paged) /l3-address-profiles` |  |
| `create_l3_address_profile(payload)` | `POST /l3-address-profiles` |  |
| `network_services(limit=…)` | `GET (paged) /network-services` |  |

## Admin users / CDGs

| Method | API call | Notes |
|---|---|---|
| `users(limit=…)` | `GET (paged) /users` |  |
| `user(user_id)` | `GET /users/{user_id}` |  |
| `create_user(payload)` | `POST /users` |  |
| `external_users(limit=…)` | `GET (paged) /users/external` |  |
| `create_external_user(payload)` | `POST /users/external` |  |
| `cdgs(limit=…)` | `GET (paged) /credential-distribution-groups` |  |
| `update_cdg(cdg_id, payload)` | `PUT /credential-distribution-groups/{cdg_id}` |  |

## Logs

| Method | API call | Notes |
|---|---|---|
| `audit_logs(limit=…)` | `GET (paged) /logs/audit` |  |

