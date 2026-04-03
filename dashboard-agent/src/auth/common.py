import asyncio
import logging

from playwright.async_api import BrowserContext, Page

from .config import EmailLoginConfig

logger = logging.getLogger(__name__)

# Max time to wait for SSO to fully complete (cert selection + device auth can be slow)
SSO_TIMEOUT = 60000


async def wait_for_sso_complete(page: Page) -> None:
    """Wait until we leave the Microsoft login domain entirely."""
    try:
        await page.wait_for_url(
            lambda url: "login.microsoftonline.com" not in url and "device.login.microsoftonline.com" not in url,
            timeout=SSO_TIMEOUT,
        )
    except Exception:
        pass


async def authenticate_sso(page: Page, internal_username: str, password: str) -> None:
    """Common SSO authentication steps. Skips if session is still valid."""
    username_field = page.get_by_role("textbox", name="username@domain.regn.net")

    try:
        await username_field.wait_for(timeout=10000)
    except Exception:
        logger.info("  → SSO session still valid, skipping login.")
        return

    logger.info("  → Entering username...")
    await username_field.fill(internal_username)
    await username_field.press("Enter")
    await page.wait_for_load_state("load")

    logger.info("  → Entering password...")
    pwd_field = page.get_by_role("textbox", name="Enter the password for")
    await pwd_field.wait_for(timeout=10000)
    await pwd_field.fill(password)
    await page.get_by_role("button", name="Sign in").click()
    logger.info("  → Authentication submitted")

    # Wait for page to settle (may redirect to device auth or stay signed in prompt)
    await page.wait_for_load_state("load")
    await asyncio.sleep(2)

    # Handle "Stay signed in?" prompt — try multiple selector patterns
    for _ in range(3):
        try:
            yes_btn = page.locator('input[value="Yes"], button:has-text("Yes"), #idSIButton9')
            if await yes_btn.is_visible(timeout=3000):
                await yes_btn.click()
                logger.info("  → Clicked 'Stay signed in'")
                await page.wait_for_load_state("load")
                break
        except Exception:
            await asyncio.sleep(1)

    # Wait until we fully leave Microsoft domains
    await wait_for_sso_complete(page)


async def handle_microsoft_account_picker(page: Page, preferred_email: str) -> None:
    """Select an account when Microsoft displays the account chooser."""
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
                logger.info("  → Selecting Microsoft account...")
                await candidate.click()
                await page.wait_for_load_state("load")
                await asyncio.sleep(1)
                return
        except Exception:
            continue


async def run_email_login_strategy(context: BrowserContext, email: str, config: EmailLoginConfig) -> bool:
    logger.info(f"  → Authenticating to {config.provider_name}...")
    page = await context.new_page()
    try:
        await page.goto(config.login_url)
        await page.wait_for_load_state("load")
        await asyncio.sleep(config.initial_wait_s)

        if config.already_logged_in(page.url):
            logger.info(f"  → Already logged into {config.provider_name}, skipping.")
            return True

        logger.info(f"  → {config.provider_name} login page URL: {page.url}")
        email_candidates = page.locator(config.email_selector)
        email_field = email_candidates.first if config.use_first_email_field else email_candidates

        try:
            await email_field.wait_for(timeout=15000)
            logger.info(f"  → Entering {config.provider_name} email...")
            await email_field.fill(email)
            await asyncio.sleep(config.email_submit_pause_s)

            submit_btn = page.locator(config.submit_selector)
            if await submit_btn.count():
                await submit_btn.first.click()
            else:
                await email_field.press("Enter")

            await page.wait_for_load_state("load")
            try:
                await page.wait_for_url(
                    lambda url: config.redirect_complete(url),
                    timeout=config.redirect_timeout_ms,
                )
                await page.wait_for_load_state("load")
                await asyncio.sleep(1)
            except Exception:
                logger.warning(
                    f"  → {config.provider_name}: redirect did not complete within "
                    f"{config.redirect_timeout_ms // 1000}s. "
                    f"Current URL: {page.url}"
                )

            logger.info(f"  → {config.provider_name} login flow ended on: {page.url}")
            return True
        except Exception as exc:
            logger.warning(f"  → {config.provider_name} login failed: {exc}")
            return False
    finally:
        await page.close()
