"""xiq-client: shared ExtremeCloud IQ / Extreme Platform ONE API client."""
from .client import PLATFORM_ONE_BASE_URL, XIQ, XIQ_BASE_URL
from .exceptions import (
    APIError,
    AuthenticationError,
    CredentialsError,
    XIQError,
)

__version__ = "0.1.0"

__all__ = [
    "XIQ",
    "XIQ_BASE_URL",
    "PLATFORM_ONE_BASE_URL",
    "XIQError",
    "CredentialsError",
    "AuthenticationError",
    "APIError",
    "__version__",
]
