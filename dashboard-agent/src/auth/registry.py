import logging

from playwright.async_api import BrowserContext, Page

from .config import AuthStrategySpec
from .email_sso_services import login_atlassian, login_cloudhealth, login_cloudzero
from .ms_sso_services import login_aipro, login_powerbi, login_sso, login_tableau, login_smartsheet

logger = logging.getLogger(__name__)


AUTH_STRATEGIES: dict[str, AuthStrategySpec] = {
    "email_only": AuthStrategySpec(
        func=login_tableau,
        requires_page=True,
        credentials=("email", "username", "password"),
    ),
    "sso": AuthStrategySpec(
        func=login_sso,
        requires_page=True,
        credentials=("username", "password"),
    ),
    "aipro": AuthStrategySpec(
        func=login_aipro,
        requires_page=True,
        credentials=("username", "password"),
    ),
    "powerbi": AuthStrategySpec(
        func=login_powerbi,
        requires_page=True,
        credentials=("username", "password"),
    ),
    "smartsheet": AuthStrategySpec(
        func=login_smartsheet,
        requires_page=True,
        credentials=("email", "username", "password"),
    ),
    # CloudHealth has been disabled
    # "cloudhealth": AuthStrategySpec(
    #     func=login_cloudhealth,
    #     requires_page=False,
    #     credentials=("cloudhealth_email",),
    #     skip_if_missing="  → Skipping cloudhealth: no credentials configured.",
    # ),
    "cloudzero": AuthStrategySpec(
        func=login_cloudzero,
        requires_page=False,
        credentials=("cloudzero_email",),
        skip_if_missing="  → Skipping cloudzero: no credentials configured.",
    ),
    "atlassian": AuthStrategySpec(
        func=login_atlassian,
        requires_page=False,
        credentials=("atlassian_email", "atlassian_token"),
        skip_if_missing="  → Skipping atlassian: no credentials configured.",
    ),
}


async def execute_auth_strategy(auth_type: str, page: Page, context: BrowserContext, creds: object) -> bool:
    """Execute a configured auth strategy while preserving current bool semantics."""
    strategy = AUTH_STRATEGIES.get(auth_type)
    if not strategy:
        logger.warning(f"  → Unknown auth_type '{auth_type}', skipping.")
        return False

    values = [getattr(creds, field, "") for field in strategy.credentials]
    if any(not value for value in values):
        if strategy.skip_if_missing:
            logger.info(strategy.skip_if_missing)
            return True

    target = page if strategy.requires_page else context
    return await strategy.func(target, *values)
