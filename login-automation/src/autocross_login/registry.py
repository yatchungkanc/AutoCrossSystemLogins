from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from .models import AuthCredentials, AuthStrategySpec
from .providers import (
    login_aipro,
    login_atlassian,
    login_cloudhealth,
    login_cloudzero,
    login_microsoft_sso,
    login_powerbi,
    login_smartsheet,
    login_tableau,
)

logger = logging.getLogger(__name__)

DEFAULT_AUTH_STRATEGIES: dict[str, AuthStrategySpec] = {
    "email_only": AuthStrategySpec(
        func=login_tableau,
        target="page",
        credentials=("email", "username", "password"),
    ),
    "sso": AuthStrategySpec(
        func=login_microsoft_sso,
        target="page",
        credentials=("username", "password"),
    ),
    "aipro": AuthStrategySpec(
        func=login_aipro,
        target="page",
        credentials=("username", "password"),
    ),
    "powerbi": AuthStrategySpec(
        func=login_powerbi,
        target="page",
        credentials=("username", "password"),
    ),
    "smartsheet": AuthStrategySpec(
        func=login_smartsheet,
        target="page",
        credentials=("email", "username", "password"),
    ),
    "cloudhealth": AuthStrategySpec(
        func=login_cloudhealth,
        target="context",
        credentials=("cloudhealth_email",),
        optional=True,
    ),
    "cloudzero": AuthStrategySpec(
        func=login_cloudzero,
        target="context",
        credentials=("cloudzero_email",),
        optional=True,
    ),
    "atlassian": AuthStrategySpec(
        func=login_atlassian,
        target="context",
        credentials=("atlassian_email", "atlassian_token"),
        optional=True,
    ),
}


class LoginDispatcher:
    """Registry-backed login wrapper for projects that select auth by name."""

    def __init__(self, strategies: Mapping[str, AuthStrategySpec] | None = None):
        self.strategies = dict(strategies or DEFAULT_AUTH_STRATEGIES)

    async def login(
        self,
        auth_type: str,
        *,
        page: Any | None = None,
        context: Any | None = None,
        credentials: AuthCredentials | object | None = None,
    ) -> bool:
        strategy = self.strategies.get(auth_type)
        if strategy is None:
            logger.warning("Unknown auth_type %r.", auth_type)
            return False

        values = [getattr(credentials, field, "") for field in strategy.credentials]
        if any(not value for value in values):
            if strategy.optional:
                logger.info("Skipping optional auth_type %r; credentials missing.", auth_type)
                return True
            logger.warning("Cannot run auth_type %r; credentials missing.", auth_type)
            return False

        target = page if strategy.target == "page" else context
        if target is None:
            logger.warning("Cannot run auth_type %r; %s target missing.", auth_type, strategy.target)
            return False

        return await strategy.func(target, *values)


async def login(
    auth_type: str,
    *,
    page: Any | None = None,
    context: Any | None = None,
    credentials: AuthCredentials | object | None = None,
    strategies: Mapping[str, AuthStrategySpec] | None = None,
) -> bool:
    """Run a named login strategy with the default dispatcher."""
    dispatcher = LoginDispatcher(strategies)
    return await dispatcher.login(
        auth_type,
        page=page,
        context=context,
        credentials=credentials,
    )

