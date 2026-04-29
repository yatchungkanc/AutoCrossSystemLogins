import asyncio
import logging

from playwright.async_api import BrowserContext

from .common import handle_microsoft_account_picker, run_email_login_strategy
from .config import CLOUDHEALTH_LOGIN, CLOUDZERO_LOGIN

logger = logging.getLogger(__name__)


async def login_cloudhealth(context: BrowserContext, email: str) -> bool:
    """Login to CloudHealth — email-only authentication."""
    return await run_email_login_strategy(context, email, CLOUDHEALTH_LOGIN)


async def login_cloudzero(context: BrowserContext, email: str) -> bool:
    """Login to CloudZero — email entry, account selection, then SSO redirect."""
    logger.info("  → Authenticating to CloudZero...")
    page = await context.new_page()
    try:
        await page.goto(CLOUDZERO_LOGIN.login_url)
        await page.wait_for_load_state("load")
        await asyncio.sleep(CLOUDZERO_LOGIN.initial_wait_s)

        if CLOUDZERO_LOGIN.already_logged_in(page.url):
            logger.info("  → Already logged into CloudZero, skipping.")
            return True

        logger.info(f"  → CloudZero login page URL: {page.url}")
        email_candidates = page.locator(CLOUDZERO_LOGIN.email_selector)
        email_field = email_candidates.first

        try:
            await email_field.wait_for(timeout=15000)
            logger.info("  → Entering CloudZero email...")
            await email_field.fill(email)
            await asyncio.sleep(CLOUDZERO_LOGIN.email_submit_pause_s)

            submit_btn = page.locator(CLOUDZERO_LOGIN.submit_selector)
            if await submit_btn.count():
                await submit_btn.first.click()
            else:
                await email_field.press("Enter")

            await page.wait_for_load_state("load")

            # On repeat logins Microsoft may show an account chooser modal.
            await handle_microsoft_account_picker(page, email)

            try:
                await page.wait_for_url(
                    lambda url: CLOUDZERO_LOGIN.redirect_complete(url),
                    timeout=CLOUDZERO_LOGIN.redirect_timeout_ms,
                )
            except Exception:
                # Retry once after another account-picker check.
                await handle_microsoft_account_picker(page, email)
                await page.wait_for_url(
                    lambda url: CLOUDZERO_LOGIN.redirect_complete(url),
                    timeout=CLOUDZERO_LOGIN.redirect_timeout_ms,
                )

            await page.wait_for_load_state("load")
            await asyncio.sleep(1)

            logger.info(f"  → CloudZero login flow ended on: {page.url}")
            return True
        except Exception as exc:
            logger.warning(f"  → CloudZero login failed: {exc}")
            return False
    finally:
        await page.close()


async def login_atlassian(context: BrowserContext, email: str, api_token: str) -> bool:
    """Authenticate to Atlassian Cloud. Tries SSO first (corporate), falls back to email/token."""
    logger.info("  → Authenticating to Atlassian...")
    page = await context.new_page()
    try:
        await page.goto("https://id.atlassian.com/login")
        await page.wait_for_load_state("load")

        # Check if already logged in (redirected away from login page)
        if "id.atlassian.com" not in page.url:
            logger.info("  → Already logged into Atlassian, skipping.")
            return True

        # Enter email
        email_field = page.locator("#username")
        try:
            await email_field.wait_for(timeout=10000)
            logger.info("  → Entering Atlassian email...")
            await email_field.fill(email)
            await page.locator("#login-submit").click()
            await page.wait_for_load_state("load")
        except Exception:
            logger.info("  → Already logged into Atlassian, skipping.")
            return True

        # Wait for redirect (SSO or password page)
        await asyncio.sleep(3)
        await page.wait_for_load_state("load")

        # If a password field appears (non-SSO), use the API token.
        # Otherwise SSO handled it via the existing Microsoft session.
        password_field = page.locator("input[type=\"password\"]")
        try:
            await password_field.wait_for(timeout=5000)
            logger.info("  → Entering Atlassian API token...")
            await password_field.fill(api_token)
            await page.get_by_role("button", name="Log in").click()
            await page.wait_for_load_state("load")
            logger.info("  → Atlassian login complete (token).")
        except Exception:
            logger.info("  → Atlassian login complete (SSO).")

        logger.info(f"  → Atlassian flow ended on: {page.url}")
        return True
    finally:
        await page.close()
