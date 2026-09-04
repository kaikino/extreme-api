"""xiq-client: shared ExtremeCloud IQ / Extreme Platform ONE API client."""
from importlib.metadata import PackageNotFoundError, version

from ._http import print_progress
from .client import PLATFORM_ONE_BASE_URL, XIQ, XIQ_BASE_URL
from .exceptions import (
    AmbiguousNameError,
    APIError,
    AuthenticationError,
    CredentialsError,
    DuplicateNameError,
    LROFailedError,
    LROTimeoutError,
    NotFoundError,
    XIQError,
)
from .lro import LROState, lro_state

try:
    __version__ = version("xiq-client")
except PackageNotFoundError:
    __version__ = "0.1.3"

__all__ = [
    "XIQ",
    "XIQ_BASE_URL",
    "PLATFORM_ONE_BASE_URL",
    "XIQError",
    "CredentialsError",
    "AuthenticationError",
    "APIError",
    "NotFoundError",
    "DuplicateNameError",
    "AmbiguousNameError",
    "LROFailedError",
    "LROTimeoutError",
    "LROState",
    "lro_state",
    "print_progress",
    "__version__",
]
