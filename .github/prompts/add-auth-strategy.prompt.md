---
description: "Scaffold a new login strategy function in strategies.py, wire credentials in loader.py, and add a dashboard entry to dashboards.yaml"
argument-hint: "Service name, auth flow (e.g. okta-sso, email-only, microsoft-sso, api-token), and any required env vars"
agent: "agent"
tools: ["read_file", "replace_string_in_file", "grep_search"]
---

Add a new auth strategy for **$ARGUMENTS** to the dashboard-agent project.

## Files to update

1. [strategies.py](../../dashboard-agent/src/auth/strategies.py) — add the login function
2. [loader.py](../../dashboard-agent/src/config/loader.py) — add new credential fields to `Credentials` and load the env vars
3. [dashboards.yaml](../../dashboard-agent/config/dashboards.yaml) — add a new entry for the dashboard

## Steps

### 1. Read existing code for context
Read all three files in full before writing anything.

### 2. Add the login function to strategies.py

Follow these conventions exactly — no exceptions:

- **Signature**: `async def login_<service>(page: Page, ...)` for browser-based flows, or `async def login_<service>(context: BrowserContext, ...)` when a new tab is needed (like `login_cloudhealth`, `login_atlassian`).
- **Session check first**: Before interacting, detect if already logged in (URL check or field visibility check with short timeout). Log `"→ Already logged in, skipping."` and return early.
- **Logging**: Use `logger.info("  → <step description>...")` for every meaningful action. Log the final URL: `logger.info(f"  → Login flow ended on: {page.url}")`.
- **`wait_for_load_state("load")`** — never `"networkidle"`.
- **Error handling**: Wrap optional/fragile steps in `try/except Exception`. Don't swallow errors on required steps.
- **Microsoft SSO**: Reuse `_authenticate_sso(page, username, password)` — do not duplicate its logic.

### 3. Add credentials to loader.py

- Add a new field to the `Credentials` dataclass with a comment showing the env var name (e.g., `service_token: str = ""  # SERVICE_TOKEN`).
- Add the corresponding `os.environ.get("SERVICE_TOKEN", "")` line in `load_credentials()`.
- Only add to the required-fields validation if the credential is mandatory for every run.

### 4. Add entry to dashboards.yaml

- Use `url:` for a single URL, `urls:` (list) for multiple. Never mix both on the same entry.
- Set `auth:` to the method name matching the new function (e.g., `login_service`).
- Follow the indentation and key order of existing entries in the file.

### 5. Output a `.env` snippet

After all code changes, print a ready-to-paste `.env` snippet showing the new env vars with placeholder values, e.g.:
```
# <Service Name>
SERVICE_EMAIL=your@email.com
SERVICE_API_TOKEN=your-token-here
```
