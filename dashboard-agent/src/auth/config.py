from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass(frozen=True)
class EmailLoginConfig:
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
class AuthStrategySpec:
    func: Callable[..., Awaitable[bool]]
    requires_page: bool
    credentials: tuple[str, ...]
    skip_if_missing: str | None = None


CLOUDHEALTH_LOGIN = EmailLoginConfig(
    provider_name="CloudHealth",
    login_url="https://apps.cloudhealthtech.com/login",
    email_selector="#email_input",
    submit_selector=(
        'button[type="submit"], input[type="submit"], '
        'button:has-text("Sign In"), button:has-text("Log In"), '
        'button:has-text("Next"), button:has-text("Continue")'
    ),
    already_logged_in=lambda url: "apps.cloudhealthtech.com" in url and "/login" not in url,
    redirect_complete=lambda url: "apps.cloudhealthtech.com" in url and "/login" not in url,
    redirect_timeout_ms=90000,  # Broadcom SSO → Microsoft → back can take >30 s
    post_redirect_stable_ms=8000,  # Allow the CloudHealth -> Broadcom -> CloudHealth cycle to settle.
)

CLOUDZERO_LOGIN = EmailLoginConfig(
    provider_name="CloudZero",
    login_url="https://app.cloudzero.com/",
    email_selector='input[type="email"], input[name="username"], input[name="email"]',
    submit_selector=(
        'button[type="submit"], input[type="submit"], '
        'button:has-text("Continue"), button:has-text("Next"), button:has-text("Sign In")'
    ),
    already_logged_in=lambda url: "auth.cloudzero.com" not in url and "/login" not in url,
    redirect_complete=lambda url: "auth.cloudzero.com" not in url and "microsoftonline.com" not in url,
    use_first_email_field=True,
)
