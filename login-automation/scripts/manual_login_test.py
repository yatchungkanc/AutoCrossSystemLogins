#!/usr/bin/env python3
"""Manual browser login tester for autocross-login.

This script launches a headed Playwright browser, runs one login strategy from
the autocross-login library, then waits so the user can inspect the browser.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from autocross_login import AuthCredentials, DEFAULT_AUTH_STRATEGIES, login


DEFAULT_PROFILE_DIR = PROJECT_ROOT / ".manual-login-profile"


def load_env_file(path: Path) -> None:
    """Load a simple KEY=VALUE env file without adding a dotenv dependency."""
    if not path.exists():
        raise FileNotFoundError(f"env file not found: {path}")

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def credentials_from_env() -> AuthCredentials:
    return AuthCredentials(
        email=os.environ.get("AUTOCROSS_EMAIL") or os.environ.get("TABLEAU_EMAIL", ""),
        username=os.environ.get("AUTOCROSS_USERNAME") or os.environ.get("SSO_USERNAME", ""),
        password=os.environ.get("AUTOCROSS_PASSWORD") or os.environ.get("SSO_PASSWORD", ""),
        atlassian_email=os.environ.get("AUTOCROSS_ATLASSIAN_EMAIL")
        or os.environ.get("ATLASSIAN_EMAIL", ""),
        atlassian_token=os.environ.get("AUTOCROSS_ATLASSIAN_TOKEN")
        or os.environ.get("ATLASSIAN_API_TOKEN", ""),
        cloudhealth_email=os.environ.get("AUTOCROSS_CLOUDHEALTH_EMAIL")
        or os.environ.get("CLOUDHEALTH_EMAIL", ""),
        cloudzero_email=os.environ.get("AUTOCROSS_CLOUDZERO_EMAIL")
        or os.environ.get("CLOUDZERO_EMAIL", ""),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch a headed Playwright browser and test one autocross-login strategy.",
    )
    parser.add_argument(
        "auth_type",
        choices=sorted(DEFAULT_AUTH_STRATEGIES),
        help="Login strategy to test.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Optional env file to load before reading credentials.",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help=f"Persistent browser profile directory. Default: {DEFAULT_PROFILE_DIR}",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chromium headless. By default the browser is visible.",
    )
    parser.add_argument(
        "--close-immediately",
        action="store_true",
        help="Close the browser immediately after the login attempt.",
    )
    parser.add_argument(
        "--landing-url",
        help=(
            "Optional URL to open after login succeeds. "
            "Can also be set with AUTOCROSS_LANDING_URL."
        ),
    )
    return parser


async def run_manual_test(args: argparse.Namespace) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "Playwright is not installed. Install it with:\n"
            '  pip install -e "login-automation[playwright]"\n'
            "  playwright install chromium",
            file=sys.stderr,
        )
        return 2

    if args.env_file:
        load_env_file(args.env_file.expanduser())

    credentials = credentials_from_env()
    strategy = DEFAULT_AUTH_STRATEGIES[args.auth_type]

    args.profile_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(args.profile_dir),
            headless=args.headless,
            viewport={"width": 1440, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()

        print(f"Testing auth_type={args.auth_type!r}")
        print(f"Using browser profile: {args.profile_dir}")
        landing_url = args.landing_url or os.environ.get("AUTOCROSS_LANDING_URL", "")
        ok = await login(
            args.auth_type,
            page=page if strategy.target == "page" else None,
            context=context if strategy.target == "context" else None,
            credentials=credentials,
            landing_url=landing_url,
        )
        print(f"Login result: {'ok' if ok else 'failed'}")

        if ok and landing_url:
            print(f"Opening landing URL: {landing_url}")
            if strategy.target == "context":
                page = await context.new_page()
            await page.goto(landing_url)
            await page.wait_for_load_state("load")

        print(f"Current page URL: {page.url}")

        if not args.close_immediately and not args.headless:
            try:
                input("Inspect the browser, then press ENTER here to close it...")
            except EOFError:
                pass

        await context.close()

    return 0 if ok else 1


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        return asyncio.run(run_manual_test(args))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Login test failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
