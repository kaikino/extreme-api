"""xiq-client: shared ExtremeCloud IQ / Extreme Platform ONE API client."""
from importlib.metadata import PackageNotFoundError, version

from .client import PLATFORM_ONE_BASE_URL, XIQ, XIQ_BASE_URL
from .exceptions import (
    APIError,
    AuthenticationError,
    CredentialsError,
    LROTimeoutError,
    XIQError,
)

try:
    __version__ = version("xiq-client")
except PackageNotFoundError:
    __version__ = "0"

__all__ = [
    "XIQ",
    "XIQ_BASE_URL",
    "PLATFORM_ONE_BASE_URL",
    "XIQError",
    "CredentialsError",
    "AuthenticationError",
    "APIError",
    "LROTimeoutError",
    "__version__",
]
