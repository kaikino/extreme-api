from __future__ import annotations

import json
import logging

import pytest
import responses

from xiq_client import (
    PLATFORM_ONE_BASE_URL,
    XIQ,
    XIQ_BASE_URL,
    APIError,
    AuthenticationError,
    CredentialsError,
    LROTimeoutError,
)

HOME = f"{XIQ_BASE_URL}/account/home"
LRO_URL = "https://api.extremecloudiq.com/operations/op-1"


def test_credentials_required(isolated_env):
    with pytest.raises(CredentialsError):
        XIQ()


def test_prefers_xiq_api_token_over_legacy(isolated_env, monkeypatch):
    monkeypatch.setenv("XIQ_API_TOKEN", "preferred")
    monkeypatch.setenv("XIQ_TOKEN", "legacy")
    client = XIQ()
    assert client.session.headers["Authorization"] == "Bearer preferred"


def test_falls_back_to_xiq_token(isolated_env, monkeypatch):
    monkeypatch.setenv("XIQ_TOKEN", "legacy")
    client = XIQ()
    assert client.session.headers["Authorization"] == "Bearer legacy"


def test_user_agent_identifies_the_client(xiq):
    assert xiq.session.headers["User-Agent"].startswith("xiq-client/")


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
def test_404_is_api_error(xiq):
    responses.add(
        responses.GET,
        f"{XIQ_BASE_URL}/devices/999",
        json={"detail": "missing"},
        status=404,
    )
    with pytest.raises(APIError) as exc:
        xiq.device(999)
    assert exc.value.status_code == 404


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
def test_paged_walks_every_page(xiq):
    responses.add(
        responses.GET,
        f"{XIQ_BASE_URL}/devices",
        json={"page": 1, "count": 1, "total_pages": 2, "data": [{"id": 1}]},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{XIQ_BASE_URL}/devices",
        json={"page": 2, "count": 1, "total_pages": 2, "data": [{"id": 2}]},
        status=200,
    )
    assert [d["id"] for d in xiq.devices(limit=1)] == [1, 2]


@responses.activate
def test_post_lro_returns_location(xiq):
    responses.add(
        responses.POST,
        f"{XIQ_BASE_URL}/account/viq/export",
        status=202,
        headers={"Location": LRO_URL},
    )
    assert xiq.post_lro("/account/viq/export") == LRO_URL


@responses.activate
def test_check_lro_is_a_single_get(xiq):
    body = {"done": False, "metadata": {"status": "RUNNING"}}
    responses.add(responses.GET, LRO_URL, json=body, status=200)
    assert xiq.check_lro(LRO_URL) == body
    assert len(responses.calls) == 1


@responses.activate
def test_wait_lro_polls_until_done(xiq):
    running = {"done": False, "metadata": {"status": "RUNNING"}}
    done = {"done": True, "metadata": {"status": "SUCCEEDED"}, "response": {"ok": True}}
    responses.add(responses.GET, LRO_URL, json=running, status=200)
    responses.add(responses.GET, LRO_URL, json=done, status=200)
    assert xiq.wait_lro(LRO_URL, timeout=10, interval=0)["response"] == {"ok": True}
    assert len(responses.calls) == 2


@responses.activate
def test_wait_lro_raises_on_failure(xiq):
    responses.add(
        responses.GET,
        LRO_URL,
        json={"done": True, "error": {"message": "boom"}, "metadata": {"status": "FAILED"}},
        status=200,
    )
    with pytest.raises(APIError) as exc:
        xiq.wait_lro(LRO_URL, timeout=10, interval=0)
    assert exc.value.body["error"]["message"] == "boom"


@responses.activate
def test_wait_lro_times_out(xiq):
    responses.add(
        responses.GET,
        LRO_URL,
        json={"done": False, "metadata": {"status": "RUNNING"}},
        status=200,
    )
    with pytest.raises(LROTimeoutError):
        xiq.wait_lro(LRO_URL, timeout=0, interval=0)


def test_jwt_on_platform_one_warns(isolated_env, caplog):
    jwt = "ey" + "a" * 20 + "." + "b" * 20 + "." + "c" * 20
    with caplog.at_level(logging.WARNING, logger="xiq_client"):
        XIQ(token=jwt, base_url=PLATFORM_ONE_BASE_URL)
    assert any("classic XIQ token" in rec.message for rec in caplog.records)


def test_platform_one_key_on_classic_host_does_not_warn(isolated_env, caplog):
    with caplog.at_level(logging.WARNING, logger="xiq_client"):
        XIQ(token="extr_sk_test", base_url=XIQ_BASE_URL)
    assert caplog.records == []


def test_user_name_alias(isolated_env):
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            f"{XIQ_BASE_URL}/login",
            json={"access_token": "from-login"},
            status=200,
        )
        client = XIQ(user_name="a@b.com", password="secret")
    assert client.session.headers["Authorization"] == "Bearer from-login"


@responses.activate
def test_select_managed_account(xiq):
    responses.add(
        responses.GET, HOME, json={"id": 1, "name": "HomeVIQ"}, status=200
    )
    responses.add(
        responses.GET,
        f"{XIQ_BASE_URL}/account/external",
        json=[{"id": 9, "name": "Ext"}],
        status=200,
    )
    accounts, name = xiq.select_managed_account()
    assert name == "HomeVIQ"
    assert accounts[0]["id"] == 9
    assert xiq.viq_name == "HomeVIQ"


@responses.activate
def test_devices_sends_repeated_hostname_params(xiq):
    responses.add(
        responses.GET,
        f"{XIQ_BASE_URL}/devices",
        json={"page": 1, "count": 0, "total_pages": 1, "data": []},
        status=200,
    )
    list(xiq.devices(hostnames=["ap-1", "ap-2"], connected=True, limit=10))
    qs = str(responses.calls[0].request.url)
    assert "hostnames=ap-1" in qs
    assert "hostnames=ap-2" in qs
    assert "connected=True" in qs or "connected=true" in qs


@responses.activate
def test_floors_for_building(xiq):
    responses.add(
        responses.GET,
        f"{XIQ_BASE_URL}/locations/building",
        json={"page": 1, "count": 1, "total_pages": 1, "data": [{"id": 50, "name": "HQ"}]},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{XIQ_BASE_URL}/locations/tree",
        json=[{"id": 51, "name": "Floor 1"}],
        status=200,
    )
    floors = xiq.floors_for_building("HQ")
    assert floors[0]["name"] == "Floor 1"


@responses.activate
def test_send_cli_wait_polls_lro(xiq):
    responses.add(
        responses.POST,
        f"{XIQ_BASE_URL}/devices/:cli",
        status=202,
        headers={"Location": LRO_URL},
    )
    responses.add(
        responses.GET,
        LRO_URL,
        json={"done": True, "metadata": {"status": "SUCCEEDED"}, "response": {"ok": 1}},
        status=200,
    )
    assert xiq.send_cli([1], ["show ver"], wait=True) == {"ok": 1}


@responses.activate
def test_assign_network_policy_accepts_json_string(xiq):
    responses.add(
        responses.POST,
        f"{XIQ_BASE_URL}/devices/network-policy/:assign",
        json={"ok": True},
        status=200,
    )
    payload = '{"devices": {"ids": ["1"]}, "network_policy_id": "9"}'
    assert xiq.assign_network_policy(payload) == {"ok": True}
    assert json.loads(responses.calls[0].request.body)["network_policy_id"] == "9"


@responses.activate
def test_deploy_config_wait_returns_status(xiq):
    responses.add(
        responses.POST,
        f"{XIQ_BASE_URL}/deployments",
        status=202,
        headers={"Location": LRO_URL},
    )
    responses.add(
        responses.GET,
        LRO_URL,
        json={"done": True, "metadata": {"status": "SUCCEEDED"}},
        status=200,
    )
    assert xiq.deploy_config([1], wait=True) == "SUCCEEDED"


@responses.activate
def test_network_policy_by_name(xiq):
    responses.add(
        responses.GET,
        f"{XIQ_BASE_URL}/network-policies",
        json={
            "page": 1,
            "count": 1,
            "total_pages": 1,
            "data": [{"id": 3, "name": "Corp"}],
        },
        status=200,
    )
    assert xiq.network_policy_by_name("Corp")["id"] == 3


@responses.activate
def test_set_device_network_policy_uses_query_param(xiq):
    responses.add(
        responses.PUT,
        f"{XIQ_BASE_URL}/devices/4/network-policy",
        json={"ok": True},
        status=200,
    )
    xiq.set_device_network_policy(4, 9)
    qs = str(responses.calls[0].request.url)
    assert "networkPolicyId=9" in qs


@responses.activate
def test_device_alarms_pass_time_filters(xiq):
    responses.add(
        responses.GET,
        f"{XIQ_BASE_URL}/devices/9/alarms",
        json={"page": 1, "count": 0, "total_pages": 1, "data": []},
        status=200,
    )
    list(xiq.device_alarms(9, startTime=1, endTime=2, limit=1))
    qs = str(responses.calls[0].request.url)
    assert "startTime=1" in qs
    assert "endTime=2" in qs

