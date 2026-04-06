# Project HotGates — Copilot Instructions

Browser automation CLI that opens multiple internal dashboards (Tableau, SharePoint, JIRA, Azure, CloudHealth) in a persistent Chromium session with SSO/token-based auth.

See [dashboard-agent/README.md](../dashboard-agent/README.md) for full architecture, setup, and design decisions.

## Project Structure

```
dashboard-agent/
  src/
    orchestrator.py         # Entry point: browser launch → login → open tabs
    cloudhealth_report.py   # CloudHealth report generator (orchestrator)
    screenshot_capture.py   # CDP screenshot capture module
    analysis.py             # Copilot CLI integration module
    report_generator.py     # HTML report generation module
    auth/
      config.py             # Auth config dataclasses (EmailLoginConfig, AuthStrategySpec)
      common.py             # Shared login helpers (Microsoft SSO flow, email flow)
      ms_sso_services.py    # MS SSO-based strategies: Tableau, SSO, AI Pro, PowerBI, Smartsheet
      email_sso_services.py # Email-submit strategies: CloudHealth, CloudZero, Atlassian
      registry.py           # AUTH_STRATEGIES registry and execute_auth_strategy()
      strategies.py         # Compatibility facade — prefer importing from auth directly
    config/loader.py        # Loads credentials from .env; validates required keys
  config/
    dashboards.yaml         # Dashboard registry: URLs, auth methods, timeouts
    prompts.yaml            # CloudHealth analysis prompts
    report_template.html    # HTML report template
  tests/                    # pytest test suite
  output/                   # Generated reports and screenshots
  .github/prompts/
    interpret-cloudhealth.prompt.md  # CloudHealth analysis prompt for Copilot
```

## Build & Run

```bash
./setup.sh                  # First time only (creates .venv, installs deps, copies .env)
source .venv/bin/activate

python run.py                                      # Launch browser with all dashboards
python run.py --list                               # List available dashboard groups
python run.py cloudhealth-report                   # Generate CloudHealth report
python run.py cloudhealth-report "cost by service" # With focus area
```

Tests live in `tests/` and use `pytest`. Run with `pytest` from `dashboard-agent/`. For async Playwright tests, use `pytest-asyncio`.

## Key Conventions

- **Python 3.11+**, async/await throughout (`async_playwright`)
- **Type hints required**: use dataclasses, `list[T]`, `Path` — no bare `dict`
- **Logging over print**: `logging.getLogger(__name__)`, level INFO
- **Auth strategies** are registered in `auth/registry.py` and dispatched via `execute_auth_strategy()`; each strategy receives a `Page` or `BrowserContext` and returns `bool` when the target page is loaded — do not assert URLs or assume redirect paths
- **`dashboards.yaml`** supports both `url` (single) and `urls` (list) per dashboard entry — new entries must handle both shapes
- **`smartsheet` auth type** uses `(email, username, password)` credentials (same fields as `email_only`); `TABLEAU_EMAIL` supplies the email
- **CloudHealth report workflow**: capture screenshots → invoke `copilot -p --allow-all-tools` (streams until process exits, no hard timeout) → strip tool-activity preamble → generate HTML → display in browser

## Critical Pitfalls

- **`.env` lives at `dashboard-agent/.env`** — not at the repo root
- **First run is manual**: user must complete device auth in browser; `rm -rf .auth_session/` to reset
- **`wait_for_load_state("load")`**, not `"networkidle"` — Tableau/SharePoint keep background requests open indefinitely
- **Do not hardcode browser paths**: use the Playwright-managed Chromium binary via `async_playwright()`
- **CDP port is fixed at 9222** for MCP browser tool compatibility
- **Context-based auth strategies (CloudHealth, Atlassian) must run sequentially** — each opens its own tab and all leftover tabs are closed before the next service starts; running them concurrently causes logins to overwrite each other
- **`login_cloudhealth` uses `wait_for_url()` with a 90 s timeout** — the SSO chain goes `apps.cloudhealthtech.com → access.broadcom.com → login.microsoftonline.com → apps.cloudhealthtech.com`; 30 s was too short for this chain. Timeout failures log the current URL instead of failing silently.
- **Set `NODE_NO_WARNINGS=1` before `async_playwright()`** — Playwright's internal Node.js server emits DEP0169 deprecation warnings; the env var must be set in the Python process before the first `async_playwright()` call so the spawned subprocess inherits it
