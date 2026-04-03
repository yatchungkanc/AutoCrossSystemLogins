import asyncio
import logging

from playwright.async_api import Page

from .common import authenticate_sso, handle_microsoft_account_picker

logger = logging.getLogger(__name__)


async def login_tableau(page: Page, tableau_email: str, sso_username: str, sso_password: str) -> bool:
    """Login to Tableau: email first, then SSO."""
    logger.info("  → Navigating to Tableau SSO page...")
    await page.goto("https://sso.online.tableau.com/public/idp/SSO")
    await page.wait_for_load_state("load")

    # Step 1: Tableau email entry (triggers redirect to SSO) — skip if already logged in
    email_field = page.get_by_role("textbox", name="Username")
    try:
        await email_field.wait_for(timeout=10000)
        logger.info("  → Entering Tableau email...")
        await email_field.fill(tableau_email)
        await page.get_by_role("button", name="Sign In").click()
        await page.wait_for_load_state("load")

        # Step 2: SSO authentication (after redirect)
        await authenticate_sso(page, sso_username, sso_password)
    except Exception:
        logger.info("  → Already logged into Tableau, skipping.")

    # Ensure we're fully done before returning
    await page.wait_for_load_state("load")
    logger.info(f"  → Login flow ended on: {page.url}")
    return True


async def login_sso(page: Page, internal_username: str, password: str) -> bool:
    """Direct SSO login."""
    await page.goto("https://sso.online.tableau.com/public/idp/SSO")
    await authenticate_sso(page, internal_username, password)
    return True


async def login_aipro(page: Page, internal_username: str, password: str) -> bool:
    """Login to AI Pro with Azure Active Directory."""
    logger.info("  → Navigating to AI Pro login page...")
    await page.goto(
        "https://aipro.elsevier.net/api/auth/signin?callbackUrl=https%3A%2F%2Flocalhost%3A3000%2F"
    )

    logger.info("  → Clicking Azure Active Directory sign-in...")
    await page.get_by_role("button", name="Sign in with Azure Active").click()

    await authenticate_sso(page, internal_username, password)

    logger.info("  → Dismissing welcome dialog...")
    await page.get_by_role("button", name="Dismiss").click()
    return True


async def login_powerbi(page: Page, username: str, password: str) -> bool:
    """Login to Power BI: handles the Microsoft email prompt, then corporate SSO."""
    logger.info("  → Navigating to Power BI...")
    await page.goto("https://app.powerbi.com/")
    await page.wait_for_load_state("load")
    await asyncio.sleep(2)

    # Microsoft sometimes shows an account-picker instead of a plain email field
    await handle_microsoft_account_picker(page, username)

    # Handle first-step email forms (Power BI or Microsoft-hosted).
    # Different tenants render different button labels, so try common variants.
    email_field = page.locator('input[type="email"]')
    try:
        await email_field.wait_for(timeout=8000)
        logger.info("  → Entering Microsoft account email for Power BI...")
        await email_field.fill(username)

        submitted = False
        for label in ("Submit", "Next", "Continue", "Sign in", "Sign In"):
            btn = page.get_by_role("button", name=label)
            try:
                if await btn.first.is_visible(timeout=1200):
                    await btn.first.click()
                    submitted = True
                    break
            except Exception:
                continue

        if not submitted:
            await email_field.press("Enter")

        await page.wait_for_load_state("load")
        await asyncio.sleep(1)

        # Some flows show account picker after the first submit.
        await handle_microsoft_account_picker(page, username)
    except Exception:
        logger.info("  → Email prompt not needed, continuing to SSO.")

    # Corporate SSO step (username@domain.regn.net + password)
    await authenticate_sso(page, username, password)

    logger.info(f"  → Power BI login flow ended on: {page.url}")
    return True
