#!/usr/bin/env python3
"""Generate METHODS.md from the XIQ class.

Every public method's docstring starts with the API call it makes
("GET (paged) /devices — ..."). This script turns those lines into the
reference table so the docs cannot drift from the code.

    python tools/gen_methods.py            # rewrite METHODS.md
    python tools/gen_methods.py --check    # exit 1 if METHODS.md is stale
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from xiq_client import XIQ  # noqa: E402
from xiq_client._http import BaseClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "METHODS.md"

# (section title, method name prefixes / explicit names, in display order)
SECTIONS: list[tuple[str, list[str]]] = [
    ("Core (works for any endpoint)", [
        "get", "post", "put", "delete", "first_page", "count", "paged", "post_lro",
        "check_lro", "lro", "wait_lro", "token", "logout", "close",
    ]),
    ("Construction & account context", [
        "from_prompt", "choose_account", "for_account", "select_managed_account",
        "switch_account", "account_home", "external_accounts", "generate_api_token",
        "token_info", "viq_info", "viq_backup", "viq_export", "viq_download", "viq_import",
    ]),
    ("Devices", [
        "devices", "device_count", "device", "device_by_serial", "device_by_hostname",
        "delete_device", "delete_devices", "unmanage_devices", "onboard_devices",
        "advanced_onboard", "reboot_device", "wait_for_device_connected", "send_cli",
        "cli_outputs", "set_hostname", "set_description", "device_location",
        "set_device_location", "move_device", "assign_location", "device_network_policy",
        "set_device_network_policy", "assign_network_policy", "device_alarms",
        "device_alarm_count", "wifi_interfaces", "radio_information",
    ]),
    ("Locations", [
        "locations_tree", "locations_flat", "init_location", "create_location", "sites",
        "site_by_name", "site_id", "create_site", "update_site", "buildings",
        "building_by_name", "building_id", "create_building", "floors",
        "floors_for_building", "floor_ids_for_building", "floor_in_building",
        "floor_ids_for_site", "devices_in_site", "devices_in_building", "devices_in_floor",
        "create_floor", "upload_floorplan", "countries", "validate_country",
    ]),
    ("End users (PPSK) / user groups / PCGs", [
        "endusers", "enduser", "enduser_by_username", "create_enduser", "update_enduser",
        "set_enduser_password", "delete_enduser", "usergroups", "usergroup_by_name",
        "usergroup_id", "pcg_users", "add_pcg_users", "add_pcg_user", "delete_pcg_users",
        "delete_pcg_user",
    ]),
    ("Network policies / deployments / SSIDs", [
        "network_policies", "network_policy_by_name", "network_policy_id", "deploy_config",
        "ssids", "ssid_by_name", "set_psk_password",
    ]),
    ("CCGs (cloud config groups)", [
        "ccgs", "ccg", "ccg_by_name", "ccg_id", "create_ccg", "update_ccg",
        "set_ccg_devices", "ccg_add_devices", "ccg_remove_devices", "delete_ccg",
    ]),
    ("Radio profiles", [
        "radio_profiles", "radio_profile", "radio_profile_by_name", "radio_usage_opt",
        "channel_selection", "radio_profile_details",
    ]),
    ("Firewall / network objects", [
        "ip_firewall_policies", "create_ip_firewall_policy", "update_ip_firewall_policy",
        "delete_ip_firewall_policy", "l3_address_profiles", "create_l3_address_profile",
        "network_services", "network_service_by_name",
    ]),
    ("Admin users / credential distribution groups", [
        "users", "user", "user_by_login", "create_user", "create_admin_user",
        "external_users", "create_external_user", "cdgs", "cdg", "cdg_by_name",
        "update_cdg", "cdg_update_payload", "cdg_add_users",
    ]),
    ("Clients / alerts / logs", [
        "active_clients", "active_client_count", "client", "client_by_mac", "alerts",
        "audit_logs",
    ]),
]

HEADER = """# Method reference

Generated from the `XIQ` class by `tools/gen_methods.py`; do not edit by hand.

Every public method, the API call behind it, and what it returns. Paths are
relative to the base URL (`https://api.extremecloudiq.com`, or the Platform
ONE equivalent). "(paged)" methods fetch every page and return a `list`.

Anything not listed is still reachable with the same retry/timeout/auth
behavior via `xiq.get/post/put/delete(path, ...)`, `xiq.paged(path, params)`,
`xiq.first_page(...)`, `xiq.count(...)`, and `xiq.post_lro(path)` +
`xiq.wait_lro(url)`.
"""

_SPLIT = re.compile(r"\s+[—-]\s+", re.M)


def _signature(name: str, member: object) -> str:
    if isinstance(inspect.getattr_static(XIQ, name), property):
        return f"`{name}`"
    try:
        sig = inspect.signature(member)
    except (TypeError, ValueError):
        return f"`{name}(...)`"
    params = [p for p in sig.parameters.values() if p.name not in ("self", "cls")]
    parts = []
    for p in params:
        if p.kind is inspect.Parameter.VAR_KEYWORD:
            parts.append("**" + p.name)
        elif p.default is inspect.Parameter.empty:
            parts.append(p.name)
        else:
            parts.append(p.name + "=…")
    return f"`{name}({', '.join(parts)})`"


def _doc_parts(member: object) -> tuple[str, str]:
    doc = inspect.getdoc(member) or ""
    # first paragraph (up to the first blank line), joined into one line
    paragraph: list[str] = []
    for line in doc.splitlines():
        if not line.strip():
            break
        paragraph.append(line.strip())
    first = " ".join(paragraph)
    pieces = _SPLIT.split(first, maxsplit=1)
    call = pieces[0].strip().rstrip(".")
    note = pieces[1].strip().rstrip(".") if len(pieces) > 1 else ""
    if not call.startswith(("GET", "POST", "PUT", "DELETE")):
        note, call = call, ""
    elif not note and ". " in call:
        call, note = (part.strip().rstrip(".") for part in call.split(". ", 1))
    return call, note


def render() -> str:
    out = [HEADER]
    listed: set[str] = set()
    for title, names in SECTIONS:
        out.append(f"\n## {title}\n")
        out.append("| Method | API call | Notes |")
        out.append("|---|---|---|")
        for name in names:
            member = getattr(XIQ, name)
            listed.add(name)
            call, note = _doc_parts(member)
            out.append(f"| {_signature(name, member)} | {_escape(call)} | {_escape(note)} |")
    public = {
        n for n, m in inspect.getmembers(XIQ)
        if not n.startswith("_")
        and (callable(m) or isinstance(inspect.getattr_static(XIQ, n), property))
    }
    missing = sorted(public - listed - {"session", "viq_name", "viq_id"})
    if missing:
        raise SystemExit(f"methods missing from SECTIONS: {missing}")
    unknown = sorted(listed - public)
    if unknown:
        raise SystemExit(f"SECTIONS names not on XIQ: {unknown}")
    return "\n".join(out) + "\n"


def _escape(text: str) -> str:
    return text.replace("|", "\\|")


def main(argv: list[str]) -> int:
    content = render()
    if "--check" in argv:
        if TARGET.read_text() != content:
            print("METHODS.md is stale; run python tools/gen_methods.py", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(content)
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    _ = BaseClient  # keep import for type reference
    raise SystemExit(main(sys.argv[1:]))
