"""Reusable async login wrappers for Playwright-based projects."""

from .models import AuthCredentials, AuthStrategySpec, EmailLoginConfig
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
from .registry import DEFAULT_AUTH_STRATEGIES, LoginDispatcher, login

__all__ = [
    "AuthCredentials",
    "AuthStrategySpec",
    "EmailLoginConfig",
    "DEFAULT_AUTH_STRATEGIES",
    "LoginDispatcher",
    "login",
    "login_aipro",
    "login_atlassian",
    "login_cloudhealth",
    "login_cloudzero",
    "login_microsoft_sso",
    "login_powerbi",
    "login_smartsheet",
    "login_tableau",
]

