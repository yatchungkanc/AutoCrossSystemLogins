# Using autocross-login in Another Project

This guide shows how to use the `autocross-login` library from a separate Python project.

The library provides reusable async login wrappers. It does not launch browsers for you, and it does not open dashboard tabs. Your project owns the Playwright browser/context lifecycle, then calls `autocross-login` to authenticate.

## 1. Decide How to Install It

### Option A: Editable Install From This Repo

Use this while developing locally:

```bash
pip install -e /path/to/AutoCrossSystemLogins/login-automation
```

If the other project does not already install Playwright:

```bash
pip install -e "/path/to/AutoCrossSystemLogins/login-automation[playwright]"
playwright install chromium
```

### Option B: Git Install

Use this when the library branch is available from Git:

```bash
pip install "autocross-login @ git+https://github.com/<org>/<repo>.git@feature/login-automation-library#subdirectory=login-automation"
playwright install chromium
```

Replace `<org>/<repo>` with the actual repository location.

## 2. Create a Browser Context

Use a persistent context if you want SSO cookies and sessions to survive across runs.

```python
from pathlib import Path
from playwright.async_api import async_playwright


PROFILE_DIR = Path(".browser-profile")


async with async_playwright() as playwright:
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=False,
        viewport={"width": 1440, "height": 900},
    )
    page = context.pages[0] if context.pages else await context.new_page()

    # Call autocross-login here.

    await context.close()
```

Use a non-persistent context only when you deliberately want a fresh login each run.

## 3. Choose Direct Wrapper or Dispatcher

Use direct wrappers when your app knows exactly which provider it is logging into.

Use the dispatcher when your app has config such as:

```yaml
auth_type: cloudzero
```

Both styles are async and return `True` or `False`.

## 4. Direct Wrapper Examples

### Power BI

Power BI is a page-based login. Pass a Playwright `Page`.

```python
from autocross_login import login_powerbi


ok = await login_powerbi(
    page,
    username="user@example.com",
    password="secret",
)
```

### CloudZero

CloudZero is context-based because it opens and closes its own temporary login page. Pass a Playwright `BrowserContext`.

```python
from autocross_login import login_cloudzero


ok = await login_cloudzero(
    context,
    email="user@example.com",
    sso_username="user@example.com",
    sso_password="secret",
    landing_url="https://app.cloudzero.com/",
)

if ok:
    page = await context.new_page()
    await page.goto("https://app.cloudzero.com/")
```

For deep links, pass the full landing URL. Quote it in shell commands if it contains `&`.

### Tableau

The Tableau wrapper uses the `email_only` flow from the original dashboard agent.

```python
from autocross_login import login_tableau


ok = await login_tableau(
    page,
    tableau_email="user@example.com",
    sso_username="user@example.com",
    sso_password="secret",
)
```

### Atlassian

Atlassian is context-based and supports SSO or API-token fallback.

```python
from autocross_login import login_atlassian


ok = await login_atlassian(
    context,
    email="user@example.com",
    api_token="token",
)
```

## 5. Dispatcher Example

The dispatcher accepts an auth type string and a credential bundle.

```python
from autocross_login import AuthCredentials, login


credentials = AuthCredentials(
    email="user@example.com",
    username="user@example.com",
    password="secret",
    cloudzero_email="user@example.com",
    atlassian_email="user@example.com",
    atlassian_token="token",
)

ok = await login(
    "cloudzero",
    context=context,
    credentials=credentials,
    landing_url="https://app.cloudzero.com/",
)
```

For page-based strategies, pass `page=page`.

```python
ok = await login(
    "powerbi",
    page=page,
    credentials=credentials,
)
```

For context-based strategies, pass `context=context`.

```python
ok = await login(
    "atlassian",
    context=context,
    credentials=credentials,
)
```

## 6. Supported Auth Types

| Auth type | Target | Required credentials |
|---|---|---|
| `email_only` | `page` | `email`, `username`, `password` |
| `sso` | `page` | `username`, `password` |
| `aipro` | `page` | `username`, `password` |
| `powerbi` | `page` | `username`, `password` |
| `smartsheet` | `page` | `email`, `username`, `password` |
| `cloudhealth` | `context` | `cloudhealth_email` |
| `cloudzero` | `context` | `cloudzero_email`; optional `username`, `password` |
| `atlassian` | `context` | `atlassian_email`, `atlassian_token` |

`cloudzero`, `cloudhealth`, and `atlassian` are optional in the dispatcher. If their credentials are missing, the dispatcher returns `True` and skips them. Required page-based auth types return `False` when credentials are missing.

## 7. Full Minimal Example

```python
import asyncio
import os
from pathlib import Path

from autocross_login import AuthCredentials, login
from playwright.async_api import async_playwright


async def main() -> None:
    credentials = AuthCredentials(
        email=os.environ.get("TABLEAU_EMAIL", ""),
        username=os.environ.get("SSO_USERNAME", ""),
        password=os.environ.get("SSO_PASSWORD", ""),
        cloudzero_email=os.environ.get("CLOUDZERO_EMAIL", ""),
    )

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(Path(".browser-profile")),
            headless=False,
            viewport={"width": 1440, "height": 900},
        )

        ok = await login(
            "cloudzero",
            context=context,
            credentials=credentials,
            landing_url="https://app.cloudzero.com/",
        )

        if ok:
            page = await context.new_page()
            await page.goto("https://app.cloudzero.com/")
            input("Inspect the browser, then press ENTER to close...")

        await context.close()


asyncio.run(main())
```

Run it:

```bash
export SSO_USERNAME="user@example.com"
export SSO_PASSWORD="secret"
export CLOUDZERO_EMAIL="user@example.com"
python example_login.py
```

## 8. Manual Smoke Test Before Integrating

From the AutoCrossSystemLogins repo:

```bash
python login-automation/scripts/manual_login_test.py cloudzero \
  --env-file dashboard-agent/.env \
  --landing-url "https://app.cloudzero.com/"
```

For a Tableau deep link:

```bash
python login-automation/scripts/manual_login_test.py email_only \
  --env-file dashboard-agent/.env \
  --landing-url "https://eu-west-1a.online.tableau.com/#/site/<site>/views/<workbook>/<view>"
```

## 9. Troubleshooting

### Import Fails

Install the package into the project environment:

```bash
pip install -e /path/to/AutoCrossSystemLogins/login-automation
```

### Playwright Browser Fails to Launch

Install Chromium:

```bash
playwright install chromium
```

### Login Stops at Microsoft SSO

Check that `username` and `password` are populated in `AuthCredentials`. CloudZero can continue through Microsoft SSO only when those optional credentials are available or the browser profile already has a valid Microsoft session.

### Login Succeeds but You See a Blank Page

Context-based wrappers may authenticate in a temporary page and close it. Open your target page after login:

```python
if ok:
    page = await context.new_page()
    await page.goto("https://app.cloudzero.com/")
```

For CloudZero, pass `landing_url` to the dispatcher or direct wrapper.

### Landing URL Goes to a Home Page

Pass the landing URL into the login call, not only into a later `page.goto()`. This lets CloudZero start the SSO flow from the requested destination:

```python
await login(
    "cloudzero",
    context=context,
    credentials=credentials,
    landing_url="https://app.cloudzero.com/explorer",
)
```

### Shell Cuts Off the Landing URL

Quote URLs that contain `&`, `?`, or `#`:

```bash
--landing-url "https://app.cloudzero.com/explorer?date_range=last_30_days&cost_type=real_cost"
```

