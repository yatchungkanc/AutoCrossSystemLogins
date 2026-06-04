from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Literal


@dataclass(frozen=True)
class EmailLoginConfig:
    """Configuration for email-first login flows that redirect to SSO."""

    provider_name: str
    login_url: str
    email_selector: str
    submit_selector: str
    already_logged_in: Callable[[str], bool]
    redirect_complete: Callable[[str], bool]
    use_first_email_field: bool = False
    initial_wait_s: int = 2
    email_submit_pause_s: int = 1
    redirect_timeout_ms: int = 30000
    post_redirect_stable_ms: int = 2000


@dataclass(frozen=True)
class AuthCredentials:
    """Credential bundle used by the dispatcher wrapper.

    Direct provider wrappers accept plain keyword arguments, so callers do not
    need this dataclass unless they want registry-style dispatch.
    """

    email: str = ""
    username: str = ""
    password: str = ""
    atlassian_email: str = ""
    atlassian_token: str = ""
    cloudhealth_email: str = ""
    cloudzero_email: str = ""


@dataclass(frozen=True)
class AuthStrategySpec:
    """Dispatcher metadata for a login strategy."""

    func: Callable[..., Awaitable[bool]]
    target: Literal["page", "context"]
    credentials: tuple[str, ...]
    optional: bool = False

