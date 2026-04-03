import asyncio
import logging
import os
import subprocess
import socket
import yaml
from pathlib import Path

# Suppress Node.js deprecation warnings emitted by Playwright's Node.js server
# (e.g. DEP0169 url.parse). Must be set before async_playwright() is called.
os.environ.setdefault("NODE_NO_WARNINGS", "1")

from playwright.async_api import async_playwright, BrowserContext, Page
from playwright.sync_api import sync_playwright as _sync_playwright

from src.config.loader import Credentials, load_credentials
from src.auth import execute_auth_strategy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "dashboards.yaml"
SESSION_DIR = Path(__file__).resolve().parents[1] / ".auth_session"
SETUP_MARKER = SESSION_DIR / ".setup_complete"
CDP_PORT = 9222  # Fixed port for MCP browser tools


def load_dashboards() -> list[dict]:
    """Flatten dashboards config into a list of {name, url, auth_type} dicts.
    Supports both single `url` and multiple `urls` per entry."""
    raw = yaml.safe_load(CONFIG_PATH.read_text())
    pages = []
    for db in raw.get("dashboards", []):
        auth_type = db.get("auth_type", "sso")
        if "urls" in db:
            for entry in db["urls"]:
                pages.append({"name": entry.get("name", db["name"]), "url": entry["url"], "auth_type": auth_type})
        elif "url" in db:
            pages.append({"name": db["name"], "url": db["url"], "auth_type": auth_type})
    return pages


def find_chromium() -> str:
    """Find the Playwright-installed Chromium binary (cross-platform)."""
    with _sync_playwright() as p:
        return p.chromium.executable_path


def get_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def launch_detached_browser(port: int, chrome: str) -> subprocess.Popen:
    """Launch Chromium as a detached process that survives script exit."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

    # Prevent "Restore pages" prompt by cleaning up crash markers
    for marker in ["Default/Sessions/Session_*", "Default/Current Session",
                   "Default/Current Tabs", "Default/Last Session", "Default/Last Tabs"]:
        for f in SESSION_DIR.glob(marker):
            f.unlink(missing_ok=True)

    # Write preferences to disable restore prompt
    prefs_dir = SESSION_DIR / "Default"
    prefs_dir.mkdir(parents=True, exist_ok=True)
    prefs_file = prefs_dir / "Preferences"
    import json
    prefs = {}
    if prefs_file.exists():
        try:
            prefs = json.loads(prefs_file.read_text())
        except Exception:
            prefs = {}
    prefs.setdefault("session", {})["restore_on_startup"] = 5  # 5 = open new tab page
    prefs.setdefault("profile", {})["exit_type"] = "Normal"
    prefs_file.write_text(json.dumps(prefs))

    proc = subprocess.Popen(
        [
            chrome,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={SESSION_DIR}",
            "--start-maximized",
            "--disable-session-crashed-bubble",
            "--hide-crash-restore-bubble",
            "--no-first-run",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc


def is_first_run() -> bool:
    return not SETUP_MARKER.exists()


async def run_setup(chrome: str):
    """First-run setup: open browser for manual login, then mark as complete."""
    port = CDP_PORT  # Changed from: get_free_port()
    dashboards = load_dashboards()
    required_auth = {db["auth_type"] for db in dashboards}
    logger.info("=== FIRST-RUN SETUP ===")
    logger.info(f"Launching browser on debug port {port}...")
    launch_detached_browser(port, chrome)
    logger.info("Waiting for browser to start...")
    await asyncio.sleep(2)

    pw = await async_playwright().start()
    browser = None
    try:
        logger.info("Connecting to browser via CDP...")
        for attempt in range(10):
            try:
                browser = await pw.chromium.connect_over_cdp(f"http://localhost:{port}")
                break
            except Exception:
                if attempt == 9:
                    raise
                logger.info(f"  → Browser not ready, retrying ({attempt + 1}/10)...")
                await asyncio.sleep(2)
        logger.info("Connected.")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else await context.new_page()

        # Navigate to Tableau SSO so user can log in manually
        logger.info("Opening Tableau SSO page — please log in manually...")
        await page.goto("https://sso.online.tableau.com/public/idp/SSO")

        logger.info("")
        logger.info("  1. Complete the Tableau / Microsoft SSO login in the browser")
        logger.info("  2. If prompted, select your certificate and click 'Stay signed in'")
        logger.info("  3. Once you see the Tableau home page, come back here")
        logger.info("")
        input("Press ENTER when Tableau login is complete...")

        # Navigate away from any device.login error page
        await page.goto("https://sso.online.tableau.com")
        await page.wait_for_load_state("load")
        logger.info(f"  → Verified Tableau session on: {page.url}")

        if "cloudzero" in required_auth:
            logger.info("Opening CloudZero login page — please log in manually...")
            await page.goto("https://app.cloudzero.com/")
            await page.wait_for_load_state("load")

            logger.info("")
            logger.info("  1. Complete CloudZero login in the browser")
            logger.info("  2. If an account chooser appears, select your logged-in account")
            logger.info("  3. Once you land on a CloudZero page, come back here")
            logger.info("")
            input("Press ENTER when CloudZero login is complete...")

            await page.wait_for_load_state("load")
            logger.info(f"  → Verified CloudZero session on: {page.url}")

        # Atlassian setup
        logger.info("Opening Atlassian login page — please log in manually...")
        await page.goto("https://id.atlassian.com/login")
        logger.info("")
        logger.info("  1. Enter your Atlassian email and complete the login")
        logger.info("  2. Or just press ENTER to skip if you don't use Atlassian")
        logger.info("")
        input("Press ENTER when Atlassian login is complete (or to skip)...")

        # Mark setup as complete
        SETUP_MARKER.touch()
        logger.info("=== SETUP COMPLETE ===")
        logger.info("Session saved. Future runs will be fully automated.")
        logger.info("Close the browser window when ready.")

    finally:
        if browser:
            browser.close = lambda: asyncio.sleep(0)
        await pw.stop()


_LOGIN_DOMAINS = (
    "login.microsoftonline.com",
    "device.login.microsoftonline.com",
    "id.atlassian.com",
    "cloudhealthtech.com/login",
    "auth.cloudzero.com",
    "accounts.google.com",
)


def _is_login_redirect(url: str) -> bool:
    return any(d in url for d in _LOGIN_DOMAINS)


async def _dispatch_auth(
    auth_type: str,
    page: Page,
    context: BrowserContext,
    creds: Credentials,
) -> bool:
    return await execute_auth_strategy(auth_type, page, context, creds)


async def run(chrome: str):
    creds = load_credentials()
    dashboards = load_dashboards()

    port = CDP_PORT  # Changed from: get_free_port()
    logger.info(f"Launching browser on debug port {port}...")
    launch_detached_browser(port, chrome)
    logger.info("Waiting for browser to start...")
    await asyncio.sleep(2)

    pw = await async_playwright().start()
    browser = None
    try:
        logger.info("Connecting to browser via CDP...")
        for attempt in range(10):
            try:
                browser = await pw.chromium.connect_over_cdp(f"http://localhost:{port}")
                break
            except Exception:
                if attempt == 9:
                    raise
                logger.info(f"  → Browser not ready, retrying ({attempt + 1}/10)...")
                await asyncio.sleep(2)
        logger.info("Connected.")
        context = browser.contexts[0]

        page = context.pages[0] if context.pages else await context.new_page()

        # Step 1: Auth — derive required strategies from dashboard auth_types, run in dependency order
        required_auth = {db["auth_type"] for db in dashboards}
        auth_results: dict[str, bool] = {}

        # Page-based strategies first (establish the Microsoft SSO session)
        for auth_type in [t for t in ("email_only", "sso", "aipro", "powerbi") if t in required_auth]:
            logger.info(f"[1/3] Authenticating: {auth_type}...")
            auth_results[auth_type] = await _dispatch_auth(auth_type, page, context, creds)
            logger.info(f"[1/3] {auth_type}: {'ok' if auth_results[auth_type] else 'FAILED'}.")

        # Context-based strategies after (open their own page, benefit from established SSO)
        # Run sequentially and clean up any lingering tabs between services so each
        # auth flow gets its own isolated window — prevents Atlassian from appearing
        # in the same tab as a still-in-progress CloudHealth SSO redirect.
        for auth_type in [t for t in ("cloudhealth", "cloudzero", "atlassian") if t in required_auth]:
            logger.info(f"[1/3] Authenticating: {auth_type}...")
            auth_results[auth_type] = await _dispatch_auth(auth_type, page, context, creds)
            logger.info(f"[1/3] {auth_type}: {'ok' if auth_results[auth_type] else 'FAILED'}.")
            # Close any extra pages (e.g. SSO popups) before the next service starts
            for p in list(context.pages):
                if p != page:
                    await p.close()

        active_page = context.pages[-1]
        await active_page.wait_for_load_state("load")

        # Close any extra pages opened during auth (keep active_page)
        for p in list(context.pages):
            if p != active_page:
                await p.close()

        # Step 2: Open all dashboard tabs in parallel
        logger.info(f"[2/3] Opening {len(dashboards)} dashboard tabs...")

        async def open_tab(db: dict, idx: int) -> dict:
            tab = active_page if idx == 0 else await context.new_page()
            try:
                await tab.goto(db["url"])
                await tab.wait_for_load_state("load")
                final_url = tab.url
                ok = not _is_login_redirect(final_url)
                if not ok:
                    logger.warning(f"  → [{db['name']}] redirected to login: {final_url}")
                else:
                    logger.info(f"  → [{db['name']}] ok")
                return {"name": db["name"], "ok": ok}
            except Exception as e:
                logger.warning(f"  → [{db['name']}] failed: {e}")
                return {"name": db["name"], "ok": False}

        results = await asyncio.gather(*[open_tab(db, i) for i, db in enumerate(dashboards)])

        # Step 3: Summary
        ok_count = sum(1 for r in results if r["ok"])
        logger.info(f"[3/3] {ok_count}/{len(results)} dashboards opened. Browser will stay open.")
        for r in results:
            logger.info(f"  {'\u2713' if r['ok'] else '\u2717'} {r['name']}")

    finally:
        # Disconnect without closing — browser stays alive
        if browser:
            browser.close = lambda: asyncio.sleep(0)
        await pw.stop()


def main():
    chrome = find_chromium()  # resolve before asyncio.run() — sync_playwright can't run inside an event loop
    if is_first_run():
        asyncio.run(run_setup(chrome))
    else:
        asyncio.run(run(chrome))


if __name__ == "__main__":
    main()
