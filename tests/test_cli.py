from __future__ import annotations

import pytest

from xiq_client import (
    APIError,
    AuthenticationError,
    CredentialsError,
    LROTimeoutError,
)
from xiq_client.cli import run, yes_no


def _run(main):
    printed: list[str] = []
    with pytest.raises(SystemExit) as exc:
        run(main, print_fn=printed.append)
    return exc.value.code, printed


def test_run_exits_zero_on_success():
    assert _run(lambda: None) == (0, [])


def test_run_uses_int_return_as_exit_code():
    assert _run(lambda: 7)[0] == 7


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (CredentialsError("no creds"), 2),
        (AuthenticationError("denied", status_code=401), 3),
        (LROTimeoutError("slow"), 4),
        (APIError("boom", status_code=500), 1),
    ],
)
def test_run_maps_errors_to_exit_codes(error, code):
    def main():
        raise error

    exit_code, printed = _run(main)
    assert exit_code == code
    assert printed == [f"error: {error}"]


def test_run_handles_keyboard_interrupt():
    def main():
        raise KeyboardInterrupt

    assert _run(main) == (130, ["interrupted"])


def test_yes_no_loops_until_valid():
    answers = iter(["maybe", "YES"])
    printed = []
    assert yes_no("Continue?", input_fn=lambda _: next(answers), print_fn=printed.append) is True
    assert printed == ["Please answer y or n."]


def test_yes_no_default():
    assert yes_no("Continue?", default=False, input_fn=lambda _: "") is False
