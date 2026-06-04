from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .models import EmailLoginConfig

logger = logging.getLogger(__name__)

MICROSOFT_LOGIN_DOMAINS = (
    "login.microsoftonline.com",
    "device.login.microsoftonline.com",
)


async def wait_for_microsoft_sso_complete(page: Any, timeout_ms: int = 60000) -> None:
    """Wait until the page leaves Microsoft login domains.

    Timeouts are tolerated because some successful enterprise SSO flows settle
    slowly or pause on a user-controlled certificate/MFA screen.
    """
    try:
        await page.wait_for_url(
            lambda url: not any(domain in url for domain in MICROSOFT_LOGIN_DOMAINS),
            timeout=timeout_ms,
        )
    except Exception:
        pass


async def authenticate_microsoft_sso(
    page: Any,
    username: str,
    password: str,
    *,
    username_textbox_name: str = "username@domain.regn.net",
    password_textbox_name: str = "Enter the password for",
    timeout_ms: int = 60000,
) -> None:
    """Enter username/password on a Microsoft SSO page when prompted.

    If the username field is not visible, the function assumes the session is
    already valid and returns without changing the page.
    """
    username_field = page.get_by_role("textbox", name=username_textbox_name)

    try:
        await username_field.wait_for(timeout=10000)
    except Exception:
        if "microsoftonline.com" in getattr(page, "url", ""):
            password_only_done = await _submit_microsoft_password_if_present(
                page,
                password,
                password_textbox_name=password_textbox_name,
            )
            if password_only_done:
                await click_stay_signed_in_if_present(page)
                await wait_for_microsoft_sso_complete(page, timeout_ms=timeout_ms)
                return

        logger.info("SSO session still valid; skipping login.")
        return

    logger.info("Entering Microsoft SSO username.")
    await username_field.fill(username)
    await username_field.press("Enter")
    await page.wait_for_load_state("load")

    await _submit_microsoft_password_if_present(
        page,
        password,
        password_textbox_name=password_textbox_name,
        timeout=10000,
    )

    await page.wait_for_load_state("load")
    await asyncio.sleep(2)

    await click_stay_signed_in_if_present(page)
    await wait_for_microsoft_sso_complete(page, timeout_ms=timeout_ms)


async def _submit_microsoft_password_if_present(
    page: Any,
    password: str,
    *,
    password_textbox_name: str,
    timeout: int = 3000,
) -> bool:
    password_field = page.get_by_role("textbox", name=password_textbox_name)
    try:
        await password_field.wait_for(timeout=timeout)
    except Exception:
        return False

    logger.info("Entering Microsoft SSO password.")
    await password_field.fill(password)
    await page.get_by_role("button", name="Sign in").click()
    return True


async def click_stay_signed_in_if_present(page: Any, attempts: int = 3) -> bool:
    """Click Microsoft's 'Stay signed in?' confirmation when it appears."""
    for _ in range(attempts):
        try:
            yes_button = page.locator('input[value="Yes"], button:has-text("Yes"), #idSIButton9')
            if await yes_button.is_visible(timeout=3000):
                await yes_button.click()
                await page.wait_for_load_state("load")
                return True
        except Exception:
            await asyncio.sleep(1)
    return False


async def select_microsoft_account(page: Any, preferred_email: str) -> bool:
    """Select an account when Microsoft displays an account chooser."""
    selectors = [
        f'text="{preferred_email}"',
        "div[role='button']:has-text('@')",
        "div.table:has-text('@')",
        "div[data-test-id='account-item']",
        "div[role='listitem']",
    ]

    for selector in selectors:
        try:
            candidate = page.locator(selector).first
            if await candidate.is_visible(timeout=1500):
                await candidate.click()
                await page.wait_for_load_state("load")
                await asyncio.sleep(1)
                return True
        except Exception:
            continue
    return False


async def run_email_login_strategy(context: Any, email: str, config: EmailLoginConfig) -> bool:
    """Run an email-submit login flow in a temporary page."""
    logger.info("Authenticating to %s.", config.provider_name)
    page = await context.new_page()
    try:
        await page.goto(config.login_url)
        await page.wait_for_load_state("load")
        await asyncio.sleep(config.initial_wait_s)

        if config.already_logged_in(page.url):
            logger.info("Already logged into %s; skipping.", config.provider_name)
            return True

        email_candidates = page.locator(config.email_selector)
        email_field = email_candidates.first if config.use_first_email_field else email_candidates

        try:
            await email_field.wait_for(timeout=15000)
            await email_field.fill(email)
            await asyncio.sleep(config.email_submit_pause_s)

            submit_button = page.locator(config.submit_selector)
            if await submit_button.count():
                await submit_button.first.click()
            else:
                await email_field.press("Enter")

            await page.wait_for_load_state("load")
            try:
                await page.wait_for_url(
                    lambda url: config.redirect_complete(url),
                    timeout=config.redirect_timeout_ms,
                )
                await wait_for_redirect_to_settle(page, config)
            except Exception:
                logger.warning(
                    "%s redirect did not complete within %ss. Current URL: %s",
                    config.provider_name,
                    config.redirect_timeout_ms // 1000,
                    page.url,
                )

            logger.info("%s login flow ended on: %s", config.provider_name, page.url)
            return True
        except Exception as exc:
            logger.warning("%s login failed: %s", config.provider_name, exc)
            return False
    finally:
        await page.close()


async def wait_for_redirect_to_settle(page: Any, config: EmailLoginConfig) -> None:
    """Require the completed redirect URL to remain stable for a short period."""
    stable_since = time.monotonic() if config.redirect_complete(page.url) else None
    deadline = time.monotonic() + max(config.post_redirect_stable_ms / 1000 * 3, 10)

    while time.monotonic() < deadline:
        current_url = page.url
        if config.redirect_complete(current_url):
            if stable_since is None:
                stable_since = time.monotonic()

            if (time.monotonic() - stable_since) * 1000 >= config.post_redirect_stable_ms:
                await page.wait_for_load_state("load")
                await asyncio.sleep(1)
                return
        else:
            stable_since = None

        await asyncio.sleep(0.5)

    logger.warning(
        "%s post-login URL did not stay stable for %ss. Current URL: %s",
        config.provider_name,
        config.post_redirect_stable_ms // 1000,
        page.url,
    )
