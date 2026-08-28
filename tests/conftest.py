"""Shared fixtures. Tests never touch the live API or the repo .env."""
from __future__ import annotations

import pytest

from xiq_client import XIQ


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in (
        "XIQ_API_TOKEN",
        "XIQ_TOKEN",
        "XIQ_USERNAME",
        "XIQ_PASSWORD",
        "XIQ_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


@pytest.fixture
def xiq(isolated_env):
    client = XIQ(token="test-token")
    client._sleep = lambda _seconds: None
    return client
