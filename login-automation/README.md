# autocross-login

Reusable async login helpers extracted from AutoCrossSystemLogins.

The package is intentionally small. It does not launch browsers or manage dashboard tabs. Callers provide their own Playwright `Page` or `BrowserContext`, then call one of the wrappers.

For a full integration walkthrough, see [Using autocross-login in Another Project](docs/using-in-another-project.md).

## Install

From this repository:

```bash
pip install -e login-automation
```

If your project does not already depend on Playwright:

```bash
pip install -e "login-automation[playwright]"
```

## Direct wrappers

```python
from autocross_login import login_powerbi

ok = await login_powerbi(page, username="user@example.com", password="secret")
```

```python
from autocross_login import login_cloudzero

ok = await login_cloudzero(context, email="user@example.com")
```

## Dispatcher wrapper

```python
from autocross_login import AuthCredentials, login

creds = AuthCredentials(
    email="user@example.com",
    username="user@example.com",
    password="secret",
    cloudzero_email="user@example.com",
)

ok = await login(
    "cloudzero",
    context=context,
    credentials=creds,
)
```

Supported strategy names:

- `email_only`
- `sso`
- `aipro`
- `powerbi`
- `smartsheet`
- `cloudhealth`
- `cloudzero`
- `atlassian`

## Design

- Async functions only.
- No browser launch or persistent profile management.
- No mandatory Playwright import at package import time.
- Provider functions return `True` on success and `False` on handled login failure.
- Unknown dispatcher strategies and missing required credentials return `False`.

## Manual Browser Test

Use the manual script to launch a visible Chromium browser and test one strategy.

```bash
pip install -e "login-automation[playwright]"
playwright install chromium
python login-automation/scripts/manual_login_test.py cloudzero --env-file dashboard-agent/.env
```

Examples:

```bash
python login-automation/scripts/manual_login_test.py powerbi --env-file dashboard-agent/.env
python login-automation/scripts/manual_login_test.py atlassian --env-file dashboard-agent/.env
python login-automation/scripts/manual_login_test.py cloudzero --env-file dashboard-agent/.env --landing-url "https://next.cloudzero.com/explorer"
```

The script uses a persistent local browser profile at `login-automation/.manual-login-profile` by default and waits for ENTER before closing the browser. For context-based logins such as CloudZero, use `--landing-url` to open a real page after authentication succeeds; otherwise the visible test page may remain blank. For CloudZero, the landing URL is also used as the initial URL for the login flow so the provider can preserve the requested destination through SSO redirects.

Quote landing URLs that contain shell-sensitive characters such as `&`:

```bash
python login-automation/scripts/manual_login_test.py cloudzero --env-file dashboard-agent/.env --landing-url "https://next.cloudzero.com/explorer?date_range=last_30_days&cost_type=real_cost"
```

You can also provide credentials directly through environment variables:

For CloudZero, the dispatcher passes `CLOUDZERO_EMAIL` plus `SSO_USERNAME` and `SSO_PASSWORD` when they are available, so the script can continue through the Microsoft SSO redirect in a fresh browser profile.

```bash
AUTOCROSS_USERNAME=user@example.com \
AUTOCROSS_PASSWORD=secret \
python login-automation/scripts/manual_login_test.py powerbi
```

Credential env fallbacks:

- `AUTOCROSS_EMAIL` or `TABLEAU_EMAIL`
- `AUTOCROSS_USERNAME` or `SSO_USERNAME`
- `AUTOCROSS_PASSWORD` or `SSO_PASSWORD`
- `AUTOCROSS_ATLASSIAN_EMAIL` or `ATLASSIAN_EMAIL`
- `AUTOCROSS_ATLASSIAN_TOKEN` or `ATLASSIAN_API_TOKEN`
- `AUTOCROSS_CLOUDZERO_EMAIL` or `CLOUDZERO_EMAIL`
- `AUTOCROSS_CLOUDHEALTH_EMAIL` or `CLOUDHEALTH_EMAIL`
- `AUTOCROSS_LANDING_URL`
