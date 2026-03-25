"""Optional integrations with sibling packages.

All integrations degrade gracefully if the sibling package is not installed.
Use ``is_available()`` on each module to check before using.
"""

from . import logger_integration
from . import cache_integration
from . import error_integration
from . import notification_integration

__all__ = [
    "logger_integration",
    "cache_integration",
    "error_integration",
    "notification_integration",
]
