from __future__ import annotations

import json
import logging
import pickle

import pytest
import requests
import responses

from xiq_client import (
    PLATFORM_ONE_BASE_URL,
    XIQ,
    XIQ_BASE_URL,
    AmbiguousNameError,
    APIError,
    AuthenticationError,
    CredentialsError,
    DuplicateNameError,
    LROFailedError,
    LROState,
    LROTimeoutError,
    NotFoundError,
    lro_state,
)

HOME = f"{XIQ_BASE_URL}/account/home"
LRO_URL = "https://api.extremecloudiq.com/operations/op-1"


def page(data, *, page_no=1, total_pages=1, total_count=None):
    return {
        "page": page_no,
        "count": len(data),
        "total_pages": total_pages,
        "total_count": len(data) if total_count is None else total_count,
        "data": data,
    }


# ---------------------------------------------------------------------------
# construction / credentials
# ---------------------------------------------------------------------------
def test_credentials_required(isolated_env):
    with pytest.raises(CredentialsError):
        XIQ()


def test_constructor_is_keyword_only(isolated_env):
    with pytest.raises(TypeError):
        XIQ("user@example.com", "secret")  # type: ignore[misc]


def test_prefers_xiq_api_token_over_legacy(isolated_env, monkeypatch):
    monkeypatch.setenv("XIQ_API_TOKEN", "preferred")
    monkeypatch.setenv("XIQ_TOKEN", "legacy")
    client = XIQ()
    assert client.session.headers["Authorization"] == "Bearer preferred"
    assert client.token == "preferred"


def test_falls_back_to_xiq_token(isolated_env, monkeypatch):
    monkeypatch.setenv("XIQ_TOKEN", "legacy")
    assert XIQ().token == "legacy"


def test_user_agent_identifies_the_client(xiq):
    assert xiq.session.headers["User-Agent"].startswith("xiq-client/")


def test_user_name_alias(isolated_env):
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            f"{XIQ_BASE_URL}/login",
            json={"access_token": "from-login"},
            status=200,
        )
        client = XIQ(user_name="a@b.com", password="secret")
    assert client.token == "from-login"


def test_jwt_on_platform_one_warns(isolated_env, caplog):
    jwt = "ey" + "a" * 20 + "." + "b" * 20 + "." + "c" * 20
    with caplog.at_level(logging.WARNING, logger="xiq_client"):
        XIQ(token=jwt, base_url=PLATFORM_ONE_BASE_URL)
    assert any("classic XIQ token" in rec.message for rec in caplog.records)


def test_platform_one_key_on_classic_host_does_not_warn(isolated_env, caplog):
    with caplog.at_level(logging.WARNING, logger="xiq_client"):
        XIQ(token="extr_sk_test", base_url=XIQ_BASE_URL)
    assert caplog.records == []


def test_from_prompt_uses_env_token(isolated_env, monkeypatch):
    monkeypatch.setenv("XIQ_API_TOKEN", "env-token")
    client = XIQ.from_prompt(input_fn=lambda _: pytest.fail("should not prompt"))
    assert client.token == "env-token"


def test_from_prompt_asks_and_retries(isolated_env):
    answers = iter(["", "a@b.com", "a@b.com"])
    passwords = iter(["", "wrong", "right"])
    printed: list[str] = []
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, f"{XIQ_BASE_URL}/login", json={"error_message": "bad"}, status=401)
        rsps.add(responses.POST, f"{XIQ_BASE_URL}/login", json={"access_token": "ok"}, status=200)
        client = XIQ.from_prompt(
            input_fn=lambda _: next(answers),
            getpass_fn=lambda _: next(passwords),
            print_fn=printed.append,
        )
    assert client.token == "ok"
    assert any("required" in line for line in printed)
    assert any("Login failed: bad" in line for line in printed)


def test_from_prompt_gives_up(isolated_env):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, f"{XIQ_BASE_URL}/login", json={}, status=401)
        with pytest.raises(CredentialsError):
            XIQ.from_prompt(
                attempts=1,
                input_fn=lambda _: "a@b.com",
                getpass_fn=lambda _: "pw",
                print_fn=lambda _: None,
            )


def test_client_pickles_with_token(xiq):
    clone = pickle.loads(pickle.dumps(xiq))
    assert clone.token == "test-token"
    assert clone.session.headers["Authorization"] == "Bearer test-token"
    assert clone.base_url == xiq.base_url


def test_context_manager_closes_the_session(isolated_env):
    closed = []
    with XIQ(token="t") as client:
        client.session.close = lambda: closed.append(True)
        assert client.token == "t"
    assert closed == [True]


# ---------------------------------------------------------------------------
# HTTP core: errors, retries
# ---------------------------------------------------------------------------
@responses.activate
def test_get_json(xiq):
    responses.add(responses.GET, HOME, json={"name": "lab"}, status=200)
    assert xiq.account_home() == {"name": "lab"}


@responses.activate
def test_401_is_authentication_error(xiq):
    responses.add(responses.GET, HOME, json={"detail": "nope"}, status=401)
    with pytest.raises(AuthenticationError) as exc:
        xiq.account_home()
    assert exc.value.status_code == 401
    assert isinstance(exc.value, APIError)


@responses.activate
def test_403_stays_authentication_error(xiq):
    responses.add(responses.GET, HOME, json={"detail": "denied"}, status=403)
    with pytest.raises(AuthenticationError) as exc:
        xiq.account_home()
    assert exc.value.status_code == 403


@responses.activate
def test_404_is_not_found_error(xiq):
    responses.add(
        responses.GET,
        f"{XIQ_BASE_URL}/devices/999",
        json={"error_code": "NOT_FOUND", "error_message": "device 999 missing"},
        status=404,
    )
    with pytest.raises(NotFoundError) as exc:
        xiq.device(999)
    assert exc.value.status_code == 404
    assert exc.value.error_message == "device 999 missing"
    assert exc.value.error_code == "NOT_FOUND"
    assert "device 999 missing" in str(exc.value)


@responses.activate
def test_duplicate_name_error(xiq):
    responses.add(
        responses.POST,
        f"{XIQ_BASE_URL}/locations/site",
        json={"error_code": "BAD_REQUEST", "error_message": "Duplicate name: HQ"},
        status=400,
    )
    with pytest.raises(DuplicateNameError):
        xiq.create_site({"name": "HQ"})


@responses.activate
def test_retries_429_and_honors_retry_after(xiq):
    responses.add(
        responses.GET,
        HOME,
        json={"detail": "slow down"},
        status=429,
        headers={"Retry-After": "0"},
    )
    responses.add(responses.GET, HOME, json={"name": "lab"}, status=200)
    assert xiq.account_home()["name"] == "lab"
    assert len(responses.calls) == 2


@responses.activate
def test_post_is_not_retried_on_500(xiq):
    responses.add(responses.POST, f"{XIQ_BASE_URL}/ccgs", json={"error_message": "boom"}, status=500)
    with pytest.raises(APIError) as exc:
        xiq.create_ccg("x")
    assert exc.value.status_code == 500
    assert len(responses.calls) == 1


@responses.activate
def test_post_is_retried_on_503(xiq):
    responses.add(responses.POST, f"{XIQ_BASE_URL}/ccgs", status=503)
    responses.add(responses.POST, f"{XIQ_BASE_URL}/ccgs", json={"id": 1}, status=201)
    assert xiq.create_ccg("x")["id"] == 1
    assert len(responses.calls) == 2


@responses.activate
def test_post_read_timeout_is_not_retried(xiq):
    responses.add(responses.POST, f"{XIQ_BASE_URL}/ccgs", body=requests.ReadTimeout("slow"))
    with pytest.raises(APIError) as exc:
        xiq.create_ccg("x")
    assert exc.value.status_code is None
    assert len(responses.calls) == 1


@responses.activate
def test_get_read_timeout_is_retried(xiq):
    responses.add(responses.GET, HOME, body=requests.ReadTimeout("slow"))
    responses.add(responses.GET, HOME, json={"name": "lab"}, status=200)
    assert xiq.account_home()["name"] == "lab"
    assert len(responses.calls) == 2


@responses.activate
def test_retry_unsafe_retries_post_timeouts(isolated_env):
    client = XIQ(token="t", retry_unsafe=True)
    client._sleep = lambda _s: None
    responses.add(responses.POST, f"{XIQ_BASE_URL}/ccgs", body=requests.ReadTimeout("slow"))
    responses.add(responses.POST, f"{XIQ_BASE_URL}/ccgs", json={"id": 1}, status=201)
    assert client.create_ccg("x")["id"] == 1


# ---------------------------------------------------------------------------
# pagination / progress
# ---------------------------------------------------------------------------
@responses.activate
def test_list_methods_return_every_page(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/devices",
                  json=page([{"id": 1}], total_pages=2, total_count=2), status=200)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/devices",
                  json=page([{"id": 2}], page_no=2, total_pages=2, total_count=2), status=200)
    devices = xiq.devices(limit=1)
    assert isinstance(devices, list)
    assert [d["id"] for d in devices] == [1, 2]


@responses.activate
def test_paged_handles_bare_list(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/l3-address-profiles", json=[{"id": 7}], status=200)
    assert xiq.l3_address_profiles(address_type="IP_ADDRESS") == [{"id": 7}]
    assert "addressType=IP_ADDRESS" in responses.calls[0].request.url


@responses.activate
def test_count_uses_one_request(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/devices/9/alarms",
                  json=page([{"id": 1}], total_pages=40, total_count=4000), status=200)
    assert xiq.device_alarm_count(9, startTime=1, endTime=2) == 4000
    assert len(responses.calls) == 1
    assert "limit=1" in responses.calls[0].request.url


@responses.activate
def test_progress_reports_pages(isolated_env):
    lines: list[str] = []
    client = XIQ(token="t", progress=lines.append)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/ccgs", json=page([{"id": 1}], total_pages=2), status=200)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/ccgs", json=page([{"id": 2}], page_no=2, total_pages=2), status=200)
    client.ccgs()
    assert lines == ["/ccgs: page 1 of 2", "/ccgs: page 2 of 2"]


@responses.activate
def test_paged_on_page_callback(xiq):
    seen = []
    responses.add(responses.GET, f"{XIQ_BASE_URL}/users", json=page([{"id": 1}, {"id": 2}]), status=200)
    list(xiq.paged("/users", on_page=lambda p, t, n: seen.append((p, t, n))))
    assert seen == [(1, 1, 2)]


# ---------------------------------------------------------------------------
# LRO
# ---------------------------------------------------------------------------
def test_lro_state_decodes_bodies():
    running = lro_state({"done": False, "metadata": {"status": "RUNNING"}})
    assert running.running and not running.done
    ok = lro_state({"done": True, "metadata": {"status": "SUCCEEDED"}, "response": {"a": 1}})
    assert ok.succeeded and ok.response == {"a": 1}
    failed = lro_state({"done": False, "metadata": {"status": "FAILED"}})
    assert failed.done and failed.failed
    errored = lro_state({"error": {"message": "x"}})
    assert errored.failed
    assert lro_state("plain").done


@responses.activate
def test_post_lro_returns_location(xiq):
    responses.add(responses.POST, f"{XIQ_BASE_URL}/account/viq/export", status=202,
                  headers={"Location": LRO_URL})
    assert xiq.viq_export() == LRO_URL


@responses.activate
def test_check_lro_is_a_single_get(xiq):
    body = {"done": False, "metadata": {"status": "RUNNING"}}
    responses.add(responses.GET, LRO_URL, json=body, status=200)
    assert xiq.check_lro(LRO_URL) == body
    assert isinstance(xiq.lro(LRO_URL), LROState)
    assert len(responses.calls) == 2


@responses.activate
def test_wait_lro_polls_until_done(xiq):
    running = {"done": False, "metadata": {"status": "RUNNING"}}
    done = {"done": True, "metadata": {"status": "SUCCEEDED"}, "response": {"ok": True}}
    responses.add(responses.GET, LRO_URL, json=running, status=200)
    responses.add(responses.GET, LRO_URL, json=done, status=200)
    polls = []
    state = xiq.wait_lro(LRO_URL, timeout=10, interval=0, on_poll=lambda s, t: polls.append(s.status))
    assert state.response == {"ok": True}
    assert polls == ["RUNNING", "SUCCEEDED"]
    assert len(responses.calls) == 2


@responses.activate
def test_wait_lro_raises_on_failure(xiq):
    responses.add(responses.GET, LRO_URL,
                  json={"done": True, "error": {"message": "boom"}, "metadata": {"status": "FAILED"}},
                  status=200)
    with pytest.raises(LROFailedError) as exc:
        xiq.wait_lro(LRO_URL, timeout=10, interval=0)
    assert isinstance(exc.value, APIError)
    assert exc.value.body["error"]["message"] == "boom"


@responses.activate
def test_wait_lro_can_return_failed_state(xiq):
    responses.add(responses.GET, LRO_URL, json={"done": True, "metadata": {"status": "FAILED"}}, status=200)
    state = xiq.wait_lro(LRO_URL, timeout=10, interval=0, raise_on_failure=False)
    assert state.failed


@responses.activate
def test_wait_lro_times_out(xiq):
    responses.add(responses.GET, LRO_URL, json={"done": False, "metadata": {"status": "RUNNING"}}, status=200)
    with pytest.raises(LROTimeoutError):
        xiq.wait_lro(LRO_URL, timeout=0, interval=0)


@responses.activate
def test_wait_lro_tolerates_transient_5xx(xiq):
    responses.add(responses.GET, LRO_URL, status=502)
    responses.add(responses.GET, LRO_URL, json={"done": True, "metadata": {"status": "SUCCEEDED"}}, status=200)
    assert xiq.wait_lro(LRO_URL, timeout=10, interval=0).succeeded


@responses.activate
def test_wait_lro_initial_delay_sleeps_first(xiq):
    slept = []
    xiq._sleep = slept.append
    responses.add(responses.GET, LRO_URL, json={"done": True, "metadata": {"status": "SUCCEEDED"}}, status=200)
    xiq.wait_lro(LRO_URL, timeout=10, interval=0, initial_delay=7)
    assert slept == [7]


# ---------------------------------------------------------------------------
# account context
# ---------------------------------------------------------------------------
@responses.activate
def test_select_managed_account(xiq):
    responses.add(responses.GET, HOME, json={"id": 1, "name": "HomeVIQ"}, status=200)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/account/external", json=[{"id": 9, "name": "Ext"}], status=200)
    accounts, name = xiq.select_managed_account()
    assert name == "HomeVIQ"
    assert accounts[0]["id"] == 9
    assert xiq.viq_name == "HomeVIQ"


@responses.activate
def test_select_managed_account_without_externals_never_raises(xiq):
    responses.add(responses.GET, HOME, json={"id": 1, "name": "HomeVIQ"}, status=200)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/account/external", json={"error_message": "nope"}, status=403)
    accounts, name = xiq.select_managed_account()
    assert accounts == []
    assert name == "HomeVIQ"


@responses.activate
def test_choose_account_switches(xiq):
    responses.add(responses.GET, HOME, json={"id": 1, "name": "HomeVIQ"}, status=200)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/account/external",
                  json=[{"id": 9, "name": "Ext"}, {"id": 10, "name": "Other"}], status=200)
    responses.add(responses.POST, f"{XIQ_BASE_URL}/account/:switch", json={"access_token": "switched"}, status=200)
    responses.add(responses.GET, HOME, json={"id": 10, "name": "Other"}, status=200)
    answers = iter(["x", "7", "1"])
    printed = []
    assert xiq.choose_account(input_fn=lambda _: next(answers), print_fn=printed.append) == "Other"
    assert xiq.token == "switched"
    assert "id=10" in responses.calls[2].request.url
    assert sum("valid number" in line for line in printed) == 2


@responses.activate
def test_choose_account_home_without_externals(xiq):
    responses.add(responses.GET, HOME, json={"id": 1, "name": "HomeVIQ"}, status=200)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/account/external", json=[], status=200)
    assert xiq.choose_account(input_fn=lambda _: pytest.fail("no prompt")) == "HomeVIQ"


@responses.activate
def test_for_account_leaves_original_alone(xiq):
    responses.add(responses.POST, f"{XIQ_BASE_URL}/account/:switch", json={"access_token": "switched"}, status=200)
    responses.add(responses.GET, HOME, json={"id": 10, "name": "Other"}, status=200)
    other = xiq.for_account(10)
    assert other.token == "switched"
    assert other.viq_name == "Other"
    assert xiq.token == "test-token"


# ---------------------------------------------------------------------------
# devices
# ---------------------------------------------------------------------------
@responses.activate
def test_devices_sends_repeated_and_camel_case_params(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/devices", json=page([]), status=200)
    xiq.devices(hostnames=["ap-1", "ap-2"], connected=True, admin_states="MANAGED",
                device_types=["REAL"], null_field="LOCATION_ID", limit=10)
    qs = responses.calls[0].request.url
    assert "hostnames=ap-1" in qs and "hostnames=ap-2" in qs
    assert "connected=true" in qs
    assert "adminStates=MANAGED" in qs
    assert "deviceTypes=REAL" in qs
    assert "nullField=LOCATION_ID" in qs
    assert "views=FULL" in qs


@responses.activate
def test_booleans_are_sent_lowercase(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/devices", json=page([]), status=200)
    xiq.devices(connected=False, config_mismatch=True)
    qs = responses.calls[0].request.url
    assert "connected=false" in qs
    assert "configMismatch=true" in qs
    assert "True" not in qs and "False" not in qs


@responses.activate
def test_booleans_inside_list_params_are_lowercase(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/locations/tree", json=[], status=200)
    xiq.locations_tree(expand_children=False)
    assert "expandChildren=false" in responses.calls[0].request.url


@responses.activate
def test_devices_fields_suppresses_views(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/devices", json=page([]), status=200)
    xiq.devices(fields=["ID", "HOSTNAME"])
    qs = responses.calls[0].request.url
    assert "fields=ID" in qs and "fields=HOSTNAME" in qs
    assert "views=" not in qs


@responses.activate
def test_devices_views_none_omits_views(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/devices", json=page([]), status=200)
    xiq.devices(views=None)
    assert "views=" not in responses.calls[0].request.url


@responses.activate
def test_devices_device_function_filters_client_side(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/devices",
                  json=page([{"id": 1, "device_function": "AP"}, {"id": 2, "device_function": "SWITCH"}]),
                  status=200)
    assert [d["id"] for d in xiq.devices(device_function="ap")] == [1]


@responses.activate
def test_device_by_serial_exact(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/devices",
                  json=page([{"id": 1, "serial_number": "ABC1"}, {"id": 2, "serial_number": "ABC"}]), status=200)
    assert xiq.device_by_serial("ABC")["id"] == 2
    assert "sns=ABC" in responses.calls[0].request.url


@responses.activate
def test_send_cli_sync_default(xiq):
    responses.add(responses.POST, f"{XIQ_BASE_URL}/devices/:cli",
                  json={"device_cli_outputs": {"5": [{"cli": "show ver", "output": "x"}]}}, status=200)
    result = xiq.send_cli([5], "show ver")
    assert "async=false" in responses.calls[0].request.url
    assert json.loads(responses.calls[0].request.body)["clis"] == ["show ver"]
    assert XIQ.cli_outputs(result) == {5: [{"cli": "show ver", "output": "x"}]}


@responses.activate
def test_send_cli_wait_polls_lro_with_delay(xiq):
    slept = []
    xiq._sleep = slept.append
    responses.add(responses.POST, f"{XIQ_BASE_URL}/devices/:cli", status=202, headers={"Location": LRO_URL})
    responses.add(responses.GET, LRO_URL, json={"done": False, "metadata": {"status": "RUNNING"}}, status=200)
    responses.add(responses.GET, LRO_URL,
                  json={"done": True, "metadata": {"status": "SUCCEEDED"},
                        "response": {"device_cli_outputs": {"1": []}}}, status=200)
    result = xiq.send_cli([1], ["show ver"], wait=True, initial_delay=3, interval=9)
    assert result == {"device_cli_outputs": {"1": []}}
    assert slept == [3, 9]


@responses.activate
def test_assign_network_policy_forms(xiq):
    responses.add(responses.POST, f"{XIQ_BASE_URL}/devices/network-policy/:assign", json={"ok": True}, status=200)
    responses.add(responses.POST, f"{XIQ_BASE_URL}/devices/network-policy/:assign", json={"ok": True}, status=200)
    xiq.assign_network_policy('{"devices": {"ids": ["1"]}, "network_policy_id": "9"}')
    assert json.loads(responses.calls[0].request.body)["network_policy_id"] == "9"
    xiq.assign_network_policy([1, 2], 9)
    assert json.loads(responses.calls[1].request.body) == {"devices": {"ids": [1, 2]}, "network_policy_id": 9}


@responses.activate
def test_assign_location_from_ids(xiq):
    responses.add(responses.POST, f"{XIQ_BASE_URL}/devices/location/:assign", json={}, status=200)
    xiq.assign_location([1, 2], 55)
    body = json.loads(responses.calls[0].request.body)
    assert body["devices"]["ids"] == [1, 2]
    assert body["device_location"]["location_id"] == 55


@responses.activate
def test_move_device_keeps_xy(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/devices/4/location", json={"location_id": 1, "x": 3, "y": 4}, status=200)
    responses.add(responses.PUT, f"{XIQ_BASE_URL}/devices/4/location", json={}, status=200)
    xiq.move_device(4, 99)
    assert json.loads(responses.calls[1].request.body) == {"location_id": 99, "x": 3, "y": 4}


@responses.activate
def test_deploy_config_wait_returns_status(xiq):
    responses.add(responses.POST, f"{XIQ_BASE_URL}/deployments", status=202, headers={"Location": LRO_URL})
    responses.add(responses.GET, LRO_URL, json={"done": True, "metadata": {"status": "SUCCEEDED"}}, status=200)
    assert xiq.deploy_config([1], wait=True, interval=0) == "SUCCEEDED"


@responses.activate
def test_deploy_config_can_report_failure(xiq):
    responses.add(responses.POST, f"{XIQ_BASE_URL}/deployments", status=202, headers={"Location": LRO_URL})
    responses.add(responses.GET, LRO_URL, json={"done": True, "metadata": {"status": "FAILED"}}, status=200)
    assert xiq.deploy_config([1], wait=True, interval=0, raise_on_failure=False) == "FAILED"


@responses.activate
def test_advanced_onboard_builds_payload_and_waits(xiq):
    responses.add(responses.POST, f"{XIQ_BASE_URL}/devices/:advanced-onboard", status=202,
                  headers={"Location": LRO_URL})
    responses.add(responses.GET, LRO_URL,
                  json={"done": True, "metadata": {"status": "SUCCEEDED"},
                        "response": {"success_devices": [{"serial_number": "S1"}]}}, status=200)
    result = xiq.advanced_onboard(extreme=[{"serial_number": "S1"}], interval=0)
    assert result["success_devices"][0]["serial_number"] == "S1"
    body = json.loads(responses.calls[0].request.body)
    assert body == {"extreme": [{"serial_number": "S1"}], "exos": [], "voss": [], "unmanaged": False}
    assert "async=true" in responses.calls[0].request.url


@responses.activate
def test_wait_for_device_connected(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/devices/4", json={"connected": False}, status=200)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/devices/4", json={"connected": True}, status=200)
    assert xiq.wait_for_device_connected(4, timeout=60, interval=0) is True
    assert len(responses.calls) == 2


@responses.activate
def test_set_device_network_policy_uses_query_param(xiq):
    responses.add(responses.PUT, f"{XIQ_BASE_URL}/devices/4/network-policy", json={"ok": True}, status=200)
    xiq.set_device_network_policy(4, 9)
    assert "networkPolicyId=9" in responses.calls[0].request.url


@responses.activate
def test_device_alarms_pass_time_filters(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/devices/9/alarms", json=page([]), status=200)
    xiq.device_alarms(9, startTime=1, endTime=2, limit=1)
    qs = responses.calls[0].request.url
    assert "startTime=1" in qs and "endTime=2" in qs


@responses.activate
def test_radio_information_chunks_ids(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/devices/radio-information", json=page([{"id": 1}]), status=200)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/devices/radio-information", json=page([{"id": 2}]), status=200)
    result = xiq.radio_information(device_ids=list(range(1, 62)))
    assert [r["id"] for r in result] == [1, 2]
    first = responses.calls[0].request.url
    assert "deviceIds=" in first and first.count("%2C") == 49


# ---------------------------------------------------------------------------
# locations
# ---------------------------------------------------------------------------
def _buildings(*names_ids):
    return page([{"id": i, "name": n} for n, i in names_ids])


@responses.activate
def test_floors_for_building_exact_match(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/locations/building",
                  json=_buildings(("HQ", 50), ("HQ-East", 51)), status=200)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/locations/tree", json=[{"id": 60, "name": "Floor 1"}], status=200)
    floors = xiq.floors_for_building("HQ")
    assert floors[0]["name"] == "Floor 1"
    assert "parentId=50" in responses.calls[1].request.url


@responses.activate
def test_floors_for_building_not_found_lists_similar(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/locations/building", json=_buildings(("HQ-East", 51)), status=200)
    with pytest.raises(NotFoundError) as exc:
        xiq.floors_for_building("HQ")
    assert "HQ-East" in str(exc.value)


@responses.activate
def test_floors_for_building_ambiguous(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/locations/building",
                  json=_buildings(("HQ", 50), ("HQ", 51)), status=200)
    with pytest.raises(AmbiguousNameError) as exc:
        xiq.building_id("HQ")
    assert len(exc.value.matches) == 2


@responses.activate
def test_floors_for_building_by_id(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/locations/tree", json=[{"id": 60, "name": "F1"}], status=200)
    assert xiq.floor_ids_for_building(50) == [60]


@responses.activate
def test_devices_in_floor_case_insensitive(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/locations/building", json=_buildings(("HQ", 50)), status=200)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/locations/tree",
                  json=[{"id": 60, "name": "Floor 1"}, {"id": 61, "name": "Floor 2"}], status=200)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/devices", json=page([{"id": 1}]), status=200)
    assert xiq.devices_in_floor("HQ", "floor 2", connected=True) == [{"id": 1}]
    assert "locationId=61" in responses.calls[2].request.url


@responses.activate
def test_devices_in_site_walks_tree(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/locations/site", json=page([{"id": 5, "name": "Campus"}]), status=200)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/locations/tree", json=[{"id": 50, "name": "B1"}], status=200)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/locations/tree", json=[{"id": 60}, {"id": 61}], status=200)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/devices", json=page([{"id": 1}]), status=200)
    assert xiq.devices_in_site("Campus") == [{"id": 1}]
    qs = responses.calls[3].request.url
    assert "locationIds=60" in qs and "locationIds=61" in qs


@responses.activate
def test_locations_flat(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/locations/tree",
                  json=[{"id": 1, "name": "Org", "type": "Location",
                         "children": [{"id": 2, "name": "B", "type": "BUILDING",
                                       "children": [{"id": 3, "name": "F", "type": "FLOOR"}]}]}],
                  status=200)
    flat = xiq.locations_flat()
    assert [(n["id"], n["parent_id"], n["path"]) for n in flat] == [
        (1, None, "Org"), (2, 1, "Org / B"), (3, 2, "Org / B / F"),
    ]


@responses.activate
def test_update_site_strips_read_only_fields(xiq):
    responses.add(responses.PUT, f"{XIQ_BASE_URL}/locations/site/5", json={}, status=200)
    site = {"id": 5, "name": "S", "create_time": 1, "org_id": 2, "unique_name": "u",
            "type": "SITE", "address": {}, "country_code": "US"}
    xiq.update_site(site, country_code="DE")
    assert json.loads(responses.calls[0].request.body) == {"name": "S", "country_code": "DE"}


@responses.activate
def test_upload_floorplan_from_path(xiq, tmp_path):
    plan = tmp_path / "plan.jpg"
    plan.write_bytes(b"jpegdata")
    responses.add(responses.POST, f"{XIQ_BASE_URL}/locations/floorplan", json={"ok": 1}, status=200)
    assert xiq.upload_floorplan(str(plan)) == {"ok": 1}
    body = responses.calls[0].request.body
    assert b"image/jpeg" in body and b"jpegdata" in body


@responses.activate
def test_countries_and_validate(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/countries", json={"data": [{"code": "US"}]}, status=200)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/countries/US/:validate", json={"valid": True}, status=200)
    assert xiq.countries() == [{"code": "US"}]
    assert xiq.validate_country("US") is True


# ---------------------------------------------------------------------------
# end users / groups / PCGs
# ---------------------------------------------------------------------------
@responses.activate
def test_endusers_group_filters(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/endusers", json=page([]), status=200)
    xiq.endusers(user_group_id=7, usernames="bob")
    qs = responses.calls[0].request.url
    assert "user_group_ids=7" in qs and "usernames=bob" in qs


@responses.activate
def test_create_enduser_keywords(xiq):
    responses.add(responses.POST, f"{XIQ_BASE_URL}/endusers", json={"id": 1}, status=200)
    xiq.create_enduser(7, name="Ann", email="ann@x.com", email_password_delivery="ann@x.com")
    assert json.loads(responses.calls[0].request.body) == {
        "user_group_id": 7, "name": "Ann", "user_name": "Ann", "password": "",
        "email_address": "ann@x.com", "email_password_delivery": "ann@x.com",
    }


@responses.activate
def test_set_enduser_password_verifies_echo(xiq):
    responses.add(responses.PUT, f"{XIQ_BASE_URL}/endusers/3", json={"password": "other"}, status=200)
    with pytest.raises(APIError):
        xiq.set_enduser_password(3, "secret")


@responses.activate
def test_usergroup_id_raises_when_missing(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/usergroups", json=page([{"id": 1, "name": "Staff"}]), status=200)
    with pytest.raises(NotFoundError) as exc:
        xiq.usergroup_id("Guests")
    assert "Staff" in str(exc.value)


@responses.activate
def test_pcg_single_user_helpers(xiq):
    responses.add(responses.POST, f"{XIQ_BASE_URL}/pcgs/key-based/network-policy-9/users", json={}, status=200)
    responses.add(responses.DELETE, f"{XIQ_BASE_URL}/pcgs/key-based/network-policy-9/users", status=202)
    xiq.add_pcg_user(9, "Ann", "ann@x.com", "Staff")
    assert json.loads(responses.calls[0].request.body) == {
        "users": [{"name": "Ann", "email": "ann@x.com", "user_group_name": "Staff"}]
    }
    xiq.delete_pcg_user(9, 42)
    assert json.loads(responses.calls[1].request.body) == {"user_ids": [42]}


# ---------------------------------------------------------------------------
# policies / CCGs / firewall / admin
# ---------------------------------------------------------------------------
@responses.activate
def test_network_policy_by_name_uses_server_filter(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/network-policies",
                  json=page([{"id": 3, "name": "Corp"}, {"id": 4, "name": "Corp-Guest"}]), status=200)
    assert xiq.network_policy_by_name("Corp")["id"] == 3
    assert "policyNames=Corp" in responses.calls[0].request.url


@responses.activate
def test_ccg_add_devices_merges(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/ccgs/8",
                  json={"id": 8, "name": "G", "description": "d", "device_ids": [1, 2]}, status=200)
    responses.add(responses.PUT, f"{XIQ_BASE_URL}/ccgs/8", json={}, status=200)
    xiq.ccg_add_devices(8, [2, 3])
    assert json.loads(responses.calls[1].request.body) == {"name": "G", "description": "d", "device_ids": [1, 2, 3]}


@responses.activate
def test_create_ccg_by_name(xiq):
    responses.add(responses.POST, f"{XIQ_BASE_URL}/ccgs", json={"id": 1}, status=201)
    xiq.create_ccg("G", device_ids=[5])
    assert json.loads(responses.calls[0].request.body) == {"name": "G", "description": "", "device_ids": [5]}


@responses.activate
def test_create_l3_address_profile_unwraps(xiq):
    responses.add(responses.POST, f"{XIQ_BASE_URL}/l3-address-profiles",
                  json={"subnet_address_profile": {"id": 9, "name": "net"}}, status=201)
    profile = xiq.create_l3_address_profile("net", address_type="IP_SUBNET", value="10.0.0.0", netmask="255.0.0.0")
    assert profile == {"id": 9, "name": "net"}
    body = json.loads(responses.calls[0].request.body)
    assert body["address_type"] == "IP_SUBNET" and body["netmask"] == "255.0.0.0"


@responses.activate
def test_create_admin_and_external_user(xiq):
    responses.add(responses.POST, f"{XIQ_BASE_URL}/users", json={"id": 1}, status=201)
    responses.add(responses.POST, f"{XIQ_BASE_URL}/users/external", json={"id": 2}, status=200)
    xiq.create_admin_user("a@x.com", "Ann")
    assert json.loads(responses.calls[0].request.body)["user_role"] == "ADMINISTRATOR"
    xiq.create_external_user("b@x.com", "OBSERVER")
    assert json.loads(responses.calls[1].request.body) == {
        "login_name": "b@x.com", "user_role": "OBSERVER", "org_id": 0, "location_ids": []
    }


@responses.activate
def test_cdg_add_users_builds_update_payload(xiq):
    cdg = {"id": 3, "name": "CDG", "enable_email_approval": False, "enable_user_limitation": True,
           "employee_group_type": "EMPLOYEE", "employee_groups": [{"name": "old@x.com"}],
           "restrict_number": 999999, "user_groups": [{"id": 7, "name": "Staff"}]}
    responses.add(responses.PUT, f"{XIQ_BASE_URL}/credential-distribution-groups/3", json={}, status=200)
    xiq.cdg_add_users(cdg, ["old@x.com", "new@x.com"])
    body = json.loads(responses.calls[0].request.body)
    assert body["employee_groups"] == [{"name": "old@x.com"}, {"name": "new@x.com"}]
    assert body["restrict_number"] == 99999
    assert body["user_group_ids"] == [7]
    assert "user_groups" not in body


@responses.activate
def test_radio_profile_details_merges(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/radio-profiles/channel-selection/2", json={"c": 1}, status=200)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/radio-profiles/radio-usage-opt/2", json={"u": 1}, status=200)
    details = xiq.radio_profile_details({"id": 2, "name": "P"})
    assert details == {"id": 2, "name": "P", "channel_selection": {"c": 1}, "radio_usage_opt": {"u": 1}}


@responses.activate
def test_active_client_count(xiq):
    responses.add(responses.GET, f"{XIQ_BASE_URL}/clients/active/count", json={"count": 12}, status=200)
    assert xiq.active_client_count(locationIds=5) == 12


@responses.activate
def test_numpy_like_ids_are_treated_as_ids(xiq):
    import numbers

    class NumpyLikeInt:  # registered as Integral but not an int, like numpy.int64
        def __init__(self, value):
            self.value = value

        def __int__(self):
            return self.value

        def __index__(self):
            return self.value

        def __str__(self):
            return str(self.value)

    numbers.Integral.register(NumpyLikeInt)
    responses.add(responses.GET, f"{XIQ_BASE_URL}/locations/tree", json=[{"id": 60}], status=200)
    assert xiq.floor_ids_for_building(NumpyLikeInt(50)) == [60]
    assert "parentId=50" in responses.calls[0].request.url


@responses.activate
def test_choose_account_accepts_prefetched_accounts(xiq):
    responses.add(responses.POST, f"{XIQ_BASE_URL}/account/:switch", json={"access_token": "sw"}, status=200)
    responses.add(responses.GET, HOME, json={"id": 9, "name": "Ext"}, status=200)
    name = xiq.choose_account(accounts=[{"id": 9, "name": "Ext"}], home="HomeVIQ",
                              input_fn=lambda _: "0", print_fn=lambda _: None)
    assert name == "Ext"
    assert responses.calls[0].request.method == "POST"  # no re-fetch of /account/external
