"""Compatibility facade for auth strategies.

The implementation is split by concern across modules:
- config.py
- common.py
- ms_sso_services.py
- email_sso_services.py
- registry.py
"""

from .registry import execute_auth_strategy

__all__ = [
    "execute_auth_strategy",
]
