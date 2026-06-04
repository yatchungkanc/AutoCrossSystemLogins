from __future__ import annotations

import asyncio
import logging
from typing import Any

from .common import (
    authenticate_microsoft_sso,
    run_email_login_strategy,
    select_microsoft_account,
)
from .models import EmailLoginConfig

logger = logging.getLogger(__name__)

DEFAULT_TABLEAU_SSO_URL = "https://sso.online.tableau.com/public/idp/SSO"
DEFAULT_AIPRO_LOGIN_URL = (
    "https://aipro.elsevier.net/api/auth/signin"
    "?callbackUrl=https%3A%2F%2Flocalhost%3A3000%2F"
)
DEFAULT_POWERBI_LOGIN_URL = "https://app.powerbi.com/"
DEFAULT_SMARTSHEET_LOGIN_URL = "https://app.smartsheet.com/"

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
    redirect_timeout_ms=90000,
    post_redirect_stable_ms=8000,
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
    redirect_timeout_ms=60000,
)


async def login_microsoft_sso(
    page: Any,
    username: str,
    password: str,
    *,
    login_url: str = DEFAULT_TABLEAU_SSO_URL,
) -> bool:
    """Navigate to a Microsoft-backed SSO start URL and authenticate."""
    await page.goto(login_url)
    await authenticate_microsoft_sso(page, username, password)
    return True


async def login_tableau(
    page: Any,
    tableau_email: str,
    sso_username: str,
    sso_password: str,
    *,
    login_url: str = DEFAULT_TABLEAU_SSO_URL,
) -> bool:
    """Log into Tableau by entering Tableau email, then Microsoft SSO credentials."""
    await page.goto(login_url)
    await page.wait_for_load_state("load")

    email_field = page.get_by_role("textbox", name="Username")
    try:
        await email_field.wait_for(timeout=10000)
        await email_field.fill(tableau_email)
        await page.get_by_role("button", name="Sign In").click()
        await page.wait_for_load_state("load")
        await authenticate_microsoft_sso(page, sso_username, sso_password)
    except Exception:
        logger.info("Already logged into Tableau; skipping email step.")

    await page.wait_for_load_state("load")
    return True


async def login_aipro(
    page: Any,
    username: str,
    password: str,
    *,
    login_url: str = DEFAULT_AIPRO_LOGIN_URL,
    dismiss_welcome: bool = True,
) -> bool:
    """Log into AI Pro through Azure Active Directory."""
    await page.goto(login_url)
    await page.get_by_role("button", name="Sign in with Azure Active").click()
    await authenticate_microsoft_sso(page, username, password)

    if dismiss_welcome:
        try:
            await page.get_by_role("button", name="Dismiss").click()
        except Exception:
            logger.info("AI Pro welcome dialog was not present.")
    return True


async def login_powerbi(
    page: Any,
    username: str,
    password: str,
    *,
    login_url: str = DEFAULT_POWERBI_LOGIN_URL,
) -> bool:
    """Log into Power BI through Microsoft SSO."""
    await page.goto(login_url)
    await page.wait_for_load_state("load")
    await asyncio.sleep(2)

    await select_microsoft_account(page, username)

    email_field = page.locator('input[type="email"]')
    try:
        await email_field.wait_for(timeout=8000)
        await email_field.fill(username)

        submitted = False
        for label in ("Submit", "Next", "Continue", "Sign in", "Sign In"):
            button = page.get_by_role("button", name=label)
            try:
                if await button.first.is_visible(timeout=1200):
                    await button.first.click()
                    submitted = True
                    break
            except Exception:
                continue

        if not submitted:
            await email_field.press("Enter")

        await page.wait_for_load_state("load")
        await asyncio.sleep(1)
        await select_microsoft_account(page, username)
    except Exception:
        logger.info("Power BI email prompt not needed.")

    await authenticate_microsoft_sso(page, username, password)
    return True


async def login_smartsheet(
    page: Any,
    email: str,
    sso_username: str,
    sso_password: str,
    *,
    login_url: str = DEFAULT_SMARTSHEET_LOGIN_URL,
) -> bool:
    """Log into Smartsheet through company account / Microsoft SSO."""
    await page.goto(login_url)
    await page.wait_for_load_state("load")

    if (
        "app.smartsheet.com" in page.url
        and "login" not in page.url.lower()
        and "microsoftonline.com" not in page.url
    ):
        return True

    if "microsoftonline.com" in page.url:
        await authenticate_microsoft_sso(page, sso_username, sso_password)
        await page.wait_for_load_state("load")
        return True

    saml_button = page.locator('[data-client-id="login-SAML-btn"]')
    try:
        await saml_button.wait_for(timeout=5000)
        await saml_button.click()
        await page.wait_for_load_state("load")
        await authenticate_microsoft_sso(page, sso_username, sso_password)
        await page.wait_for_load_state("load")
        return True
    except Exception:
        pass

    email_field = page.locator("#loginEmail")
    try:
        await email_field.wait_for(timeout=10000)
        await email_field.fill(email)

        submitted = False
        for label in ("Sign In", "Sign in", "Next", "Continue", "Log In"):
            button = page.get_by_role("button", name=label)
            try:
                if await button.first.is_visible(timeout=1200):
                    await button.first.click()
                    submitted = True
                    break
            except Exception:
                continue

        if not submitted:
            await email_field.first.press("Enter")

        await page.wait_for_load_state("load")
        await authenticate_microsoft_sso(page, sso_username, sso_password)
    except Exception:
        logger.info("Already logged into Smartsheet; skipping email step.")

    await page.wait_for_load_state("load")
    return True


async def login_cloudhealth(context: Any, email: str) -> bool:
    """Log into CloudHealth using an email-first SSO redirect flow."""
    return await run_email_login_strategy(context, email, CLOUDHEALTH_LOGIN)


async def login_cloudzero(
    context: Any,
    email: str,
    sso_username: str = "",
    sso_password: str = "",
    landing_url: str = "",
) -> bool:
    """Log into CloudZero through email entry and optional Microsoft SSO."""
    page = await context.new_page()
    try:
        await page.goto(landing_url or CLOUDZERO_LOGIN.login_url)
        await page.wait_for_load_state("load")
        await asyncio.sleep(CLOUDZERO_LOGIN.initial_wait_s)

        if CLOUDZERO_LOGIN.already_logged_in(page.url):
            return True

        email_field = page.locator(CLOUDZERO_LOGIN.email_selector).first
        try:
            await email_field.wait_for(timeout=15000)
            await email_field.fill(email)
            await asyncio.sleep(CLOUDZERO_LOGIN.email_submit_pause_s)

            submit_button = page.locator(CLOUDZERO_LOGIN.submit_selector)
            if await submit_button.count():
                await submit_button.first.click()
            else:
                await email_field.press("Enter")

            await page.wait_for_load_state("load")
            await select_microsoft_account(page, email)
            await _authenticate_if_on_microsoft_sso(page, sso_username, sso_password)

            try:
                await page.wait_for_url(
                    lambda url: CLOUDZERO_LOGIN.redirect_complete(url),
                    timeout=CLOUDZERO_LOGIN.redirect_timeout_ms,
                )
            except Exception:
                await select_microsoft_account(page, email)
                await _authenticate_if_on_microsoft_sso(page, sso_username, sso_password)
                await page.wait_for_url(
                    lambda url: CLOUDZERO_LOGIN.redirect_complete(url),
                    timeout=CLOUDZERO_LOGIN.redirect_timeout_ms,
                )

            await page.wait_for_load_state("load")
            await asyncio.sleep(1)
            if landing_url and page.url != landing_url:
                await page.goto(landing_url)
                await page.wait_for_load_state("load")
            return True
        except Exception as exc:
            logger.warning("CloudZero login failed: %s", exc)
            return False
    finally:
        await page.close()


async def _authenticate_if_on_microsoft_sso(
    page: Any,
    sso_username: str,
    sso_password: str,
) -> None:
    if not sso_username or not sso_password:
        return
    if "microsoftonline.com" not in page.url:
        return

    await authenticate_microsoft_sso(page, sso_username, sso_password)


async def login_atlassian(context: Any, email: str, api_token: str) -> bool:
    """Log into Atlassian Cloud using SSO or an API token fallback."""
    page = await context.new_page()
    try:
        await page.goto("https://id.atlassian.com/login")
        await page.wait_for_load_state("load")

        if "id.atlassian.com" not in page.url:
            return True

        email_field = page.locator("#username")
        try:
            await email_field.wait_for(timeout=10000)
            await email_field.fill(email)
            await page.locator("#login-submit").click()
            await page.wait_for_load_state("load")
        except Exception:
            return True

        await asyncio.sleep(3)
        await page.wait_for_load_state("load")

        password_field = page.locator('input[type="password"]')
        try:
            await password_field.wait_for(timeout=5000)
            await password_field.fill(api_token)
            await page.get_by_role("button", name="Log in").click()
            await page.wait_for_load_state("load")
        except Exception:
            logger.info("Atlassian login completed through SSO.")

        return True
    finally:
        await page.close()
