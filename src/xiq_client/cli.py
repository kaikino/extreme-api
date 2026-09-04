"""Helpers for scripts that run from a terminal.

::

    from xiq_client import XIQ
    from xiq_client.cli import run

    def main():
        xiq = XIQ.from_prompt()      # token from env, else Email/Password prompt
        xiq.choose_account()         # numbered VIQ menu (no-op without external accounts)
        for d in xiq.devices(connected=True):
            print(d["hostname"])

    if __name__ == "__main__":
        run(main)                    # prints xiq-client errors cleanly, exits non-zero
"""
from __future__ import annotations

import sys
from typing import Any, Callable, NoReturn

from ._http import print_progress
from .exceptions import (
    AuthenticationError,
    CredentialsError,
    LROTimeoutError,
    XIQError,
)

__all__ = ["run", "print_progress", "yes_no", "EXIT_OK", "EXIT_ERROR",
           "EXIT_CREDENTIALS", "EXIT_AUTH", "EXIT_TIMEOUT", "EXIT_INTERRUPTED"]

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CREDENTIALS = 2
EXIT_AUTH = 3
EXIT_TIMEOUT = 4
EXIT_INTERRUPTED = 130


def _exit_code(exc: XIQError) -> int:
    if isinstance(exc, CredentialsError):
        return EXIT_CREDENTIALS
    if isinstance(exc, AuthenticationError):
        return EXIT_AUTH
    if isinstance(exc, LROTimeoutError):
        return EXIT_TIMEOUT
    return EXIT_ERROR


def run(
    main: Callable[[], Any],
    *,
    print_fn: Callable[[str], None] | None = None,
) -> NoReturn:
    """Call ``main()`` and turn xiq-client errors into a message and exit code.

    * :class:`CredentialsError` -> exit 2
    * :class:`AuthenticationError` -> exit 3
    * :class:`LROTimeoutError` -> exit 4
    * any other :class:`XIQError` -> exit 1
    * ``KeyboardInterrupt`` -> exit 130

    ``main`` may return an int to use as the exit code. Errors are printed
    to stderr as ``error: <message>`` unless ``print_fn`` is given.
    """
    emit = print_fn or (lambda msg: print(msg, file=sys.stderr, flush=True))
    try:
        result = main()
    except KeyboardInterrupt:
        emit("interrupted")
        sys.exit(EXIT_INTERRUPTED)
    except XIQError as exc:
        emit(f"error: {exc}")
        sys.exit(_exit_code(exc))
    sys.exit(result if isinstance(result, int) else EXIT_OK)


def yes_no(
    question: str,
    *,
    default: bool | None = None,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> bool:
    """Ask a y/n question until the answer is valid."""
    hint = "y/n" if default is None else ("Y/n" if default else "y/N")
    while True:
        answer = input_fn(f"{question} ({hint}): ").strip().lower()
        if not answer and default is not None:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print_fn("Please answer y or n.")
