# Dashboard Monitoring Agent

Automated browser agent that logs into internal dashboards via Microsoft SSO and Atlassian, then opens them all as tabs in a single maximized browser window. Built with Python and Playwright.

## Problem

A manager needs to monitor multiple internal dashboards daily — Tableau views, SharePoint Excel files, JIRA/Confluence pages. Each requires navigating to a URL, authenticating via SSO or Atlassian, and manually switching between them. This agent automates the entire flow.

## How It Works

```
First run (setup mode):
  1. Launch maximized Chromium with persistent session
  2. Open Tableau SSO page — user logs in manually (cert selection, MFA, etc.)
  3. Open Atlassian login page — user logs in manually (if configured)
  4. Save .setup_complete marker — future runs are fully automated

Subsequent runs (automated):
  [1/3]  Tableau login: email → Microsoft SSO → username + password → "Stay signed in?"
  [1b/3] Atlassian login: email → SSO redirect (or API token fallback)
  [2/3]  Open each dashboard as a browser tab (tab 1/8, 2/8, ... 8/8)
  [3/3]  Script exits — browser stays open for the manager
```

Login steps are automatically skipped if the session is still valid.

## Architecture

The browser is launched as a **detached subprocess** (`start_new_session=True`) so it survives script exit. Playwright connects via **Chrome DevTools Protocol (CDP)**, performs authentication and tab management, then disconnects without killing the browser. This is a fire-and-forget design — the script exits after opening all tabs.

```
orchestrator.py
  ├── launch_detached_browser()  →  subprocess.Popen (Chromium)
  ├── connect_over_cdp()         →  Playwright connects to running browser
  ├── login strategies           →  auth via existing browser pages
  ├── open dashboard tabs        →  new tabs for each URL
  └── pw.stop()                  →  disconnect (browser stays alive)
```

## Project Structure

```
projectHotGates/
├── .gitignore
├── setup.sh                               # One-liner bootstrap (venv + deps + .env)
├── run.py                                 # Main entry point
└── dashboard-agent/
    ├── .env                           # Credentials (not committed)
    ├── .env.example                   # Template
    ├── config/
    │   ├── dashboards.yaml            # Dashboard registry (add URLs here)
    │   ├── prompts.yaml               # CloudHealth analysis prompts
    │   └── report_template.html       # HTML report template
    ├── src/
    │   ├── auth/
    │   │   ├── config.py              # Auth config dataclasses (EmailLoginConfig, AuthStrategySpec)
    │   │   ├── common.py              # Shared login helpers (MS SSO flow, email flow)
    │   │   ├── ms_sso_services.py     # MS SSO strategies: Tableau, SSO, AI Pro, PowerBI
    │   │   ├── email_sso_services.py  # Email-submit strategies: CloudHealth, CloudZero, Atlassian
    │   │   ├── registry.py            # AUTH_STRATEGIES registry and execute_auth_strategy()
    │   │   └── strategies.py          # Compatibility facade
    │   ├── config/
    │   │   └── loader.py              # Loads credentials from .env
    │   ├── orchestrator.py            # Main browser session manager
    │   ├── cloudhealth_report.py      # Report generation agent (orchestrator)
    │   ├── screenshot_capture.py      # Screenshot capture module
    │   ├── analysis.py                # Copilot CLI integration module
    │   └── report_generator.py        # HTML report generation module
    ├── tests/                         # pytest test suite
    ├── output/                        # Generated reports
    │   └── temp/                      # Temporary files (auto-cleaned)
    ├── .auth_session/                 # Persistent browser profile (auto-created)
    │   ├── .setup_complete            # First-run setup marker
    │   └── Default/Preferences        # Chromium prefs (auto-managed)
    ├── pyproject.toml                 # Dependencies
    └── README.md
```

## Setup

### Prerequisites

- Python 3.11+
- Chromium (installed via Playwright)

### Quick start (from repo root)

```bash
./setup.sh
```

This single command:
1. Creates a `.venv` virtual environment at the repo root
2. Installs all dependencies from `dashboard-agent/pyproject.toml`
3. Downloads the Playwright-managed Chromium binary
4. Copies `dashboard-agent/.env.example` → `dashboard-agent/.env` (if not already present)

After setup:

```bash
source .venv/bin/activate
python run.py                          # open all dashboards
python run.py --list                   # list available dashboard groups
python run.py cloudhealth-report       # generate CloudHealth report
```

### Manual installation

```bash
cd dashboard-agent
pip install -e .
playwright install chromium
```

### Credentials

Copy `dashboard-agent/.env.example` to `dashboard-agent/.env` and fill in your values (or run `./setup.sh` — it copies the file automatically):

```env
# Company SSO
SSO_USERNAME=<username>@domain.net
SSO_PASSWORD=<password>

# Tableau
TABLEAU_EMAIL=<email>

# Atlassian API token for JIRA access
ATLASSIAN_EMAIL=<email>
ATLASSIAN_API_TOKEN=<api_token>

# CloudHealth (optional)
CLOUDHEALTH_EMAIL=<email>

# CloudZero (optional)
CLOUDZERO_EMAIL=<email>
```

- No quotes needed around values
- Never commit the `.env` file to version control
- The `.env` file must be at `dashboard-agent/.env` — the loader resolves the path relative to `src/config/loader.py`
- Generate an Atlassian API token at https://id.atlassian.com/manage-profile/security/api-tokens

### First-Run Setup

On the first run (no `.setup_complete` marker), the agent enters guided setup mode. No `.env` file is needed for this step.

```bash
source .venv/bin/activate   # activate the venv created by setup.sh
python run.py
```

The browser opens and you'll be prompted to:
1. Complete the Tableau / Microsoft SSO login manually (including certificate selection)
2. Complete the Atlassian login manually (or press ENTER to skip)
3. Press ENTER in the terminal after each step

This is necessary because the first Microsoft SSO login may trigger `device.login.microsoftonline.com` which requires a client certificate the automated flow can't handle. Once setup completes, a `.setup_complete` marker is saved and all future runs are fully automated.

After setup, create your `.env` file for automated runs (see [Credentials](#credentials)).

To re-run setup:

```bash
rm -rf dashboard-agent/.auth_session/
python run.py
```

## Usage

```bash
source .venv/bin/activate
python run.py                                # open all dashboards
python run.py --list                         # list available dashboard groups
python run.py <id-or-name> [<id-or-name>...] # open matching dashboard groups only
python run.py cloudhealth-report             # generate CloudHealth report
```

The agent will:
1. Launch a maximized Chromium browser (detached subprocess)
2. Connect via CDP and authenticate (or skip if session is valid)
3. Open all configured dashboards as tabs with progress logging
4. Disconnect and exit — browser stays open for you to use

Example output:

```
Launching browser on debug port 52431...
Waiting for browser to start...
Connecting to browser via CDP...
Connected.
[1/3] Authenticating Tableau via SSO...
  → SSO session still valid, skipping login.
[1/3] Tableau login complete.
[1b/3] Authenticating Atlassian...
  → Already logged into Atlassian, skipping.
[1b/3] Atlassian login complete.
[2/3] Opening tab 1/8: AWS Account Vulnerability Trends...
  → Landed on AWS Account Vulnerability Trends.
[2/3] Opening tab 2/8: AWS Account Vulnerability Age Breakdown...
  → Landed on AWS Account Vulnerability Age Breakdown.
...
[3/3] All 8 dashboards open. Script exiting — browser will stay open.
```

## CloudHealth Report Generator

The CloudHealth report generator automatically captures dashboard screenshots and uses the Copilot CLI to analyze them in non-interactive mode, generating a comprehensive HTML report with cost optimization insights.

**Architecture**: Modular agent-based design with configuration-driven prompts and templates.

### Usage

```bash
# 1. Ensure orchestrator is running with browser session
python run.py

# 2. Generate the CloudHealth report (fully automated)
python run.py cloudhealth-report

# Optional: focus on specific areas (comma-separated)
python run.py cloudhealth-report "cost by service, anomaly detection"
```

The analysis runs automatically using `copilot -p` in non-interactive mode. No manual intervention required!

### Architecture & Modules

The report generator is split into four modules for maintainability and testability:

1. **`screenshot_capture.py`**: Browser connection and full-page screenshot capture
   - Connects to CDP port 9222
   - Scrolling capture with configurable overlap
   - Temporary file management

2. **`analysis.py`**: Copilot CLI integration and prompt construction
   - Loads prompts from `config/prompts.yaml`
   - Invokes `copilot -p --allow-all-tools` and streams output until the process exits (no hard timeout)
   - Strips Copilot tool-activity preamble before the analysis markdown begins

3. **`report_generator.py`**: HTML report generation
   - Markdown to HTML conversion
   - Template substitution from `config/report_template.html`
   - Severity indicator styling

4. **`cloudhealth_report.py`**: Main agent orchestrator
   - Progress tracking and logging
   - Error recovery with fallbacks
   - Automatic cleanup of temporary files

**Configuration files** (externalized from code):
- `config/prompts.yaml`: Analysis prompts and focus instructions
- `config/report_template.html`: HTML template with Jinja2-style placeholders
- `config/dashboards.yaml`: Dashboard URLs and authentication

### Workflow

1. **Verify Browser**: Check CDP connection to orchestrator session
2. **Capture Screenshots**: Full-page scrolling capture with lazy-load triggering
   - Scrolls to bottom repeatedly until content height stabilizes
   - Captures all dynamically loaded charts and widgets
   - Systematic capture from top to bottom with 20% overlap
3. **Analyze**: Invoke Copilot CLI with built prompt (streams until process exits — no hard timeout)
   - Uses `--allow-all-tools` so Copilot can read the screenshot files directly
   - **Fails fast** if Copilot CLI is unavailable or exits with a non-zero code
   - No silent fallbacks — errors are fatal and clearly reported
4. **Generate Report**: Convert analysis to HTML using template
5. **Cleanup**: Remove temporary screenshot directory
6. **Display**: Open report in new browser tab

**Fail-fast behavior** — if Copilot CLI is not installed or analysis fails, the script exits with a clear error message. No placeholder reports generated.

### Analysis Guidelines

The report follows the CloudHealth interpretation prompt guidelines:
- **Cost by Accounts**: 6-month trend analysis with specific values and percentage changes
- **Cost by Service**: Top 5 resources, spike identification (>20% increases)
- **Executive Summary**: Overall spend status, critical alerts, recommendations with estimated savings

### Prerequisites

**Required:**
- GitHub Copilot CLI must be installed and in your PATH
- Orchestrator browser session must be running

Install Copilot CLI:
```bash
# Via GitHub CLI extension
gh extension install github/gh-copilot

# Or download directly from https://github.com/github/copilot-cli
```

**Behavior**: The script will fail with a clear error if Copilot CLI is not available. This is intentional - the tool is designed for automated analysis, not manual workflows.

### Output Structure

```
dashboard-agent/
  config/
    prompts.yaml              # Analysis prompts and focus instructions
    report_template.html      # HTML template with styled layout
    dashboards.yaml           # Dashboard URLs
  output/
    cloudhealth_report_20260320_143022.html  # Generated reports (persistent)
    temp/                     # Temporary files (auto-cleaned after successful run)
      capture_20260320_143022/
        screenshots_*/        # Screenshots (deleted after report generation)
```

**Cleanup behavior**: Screenshot temporary directories are automatically removed after successful report generation. Only the final HTML report persists.

### Report Contents

The generated HTML report includes:
- **Dashboard metadata**: Title, URL, capture timestamp
- **Analysis sections**: Cost by Accounts, Cost by Service, Executive Summary
- **Severity indicators**: Visual badges for critical/warning/info/positive findings
- **Professional styling**: Responsive layout with syntax highlighting
- **Markdown formatting**: Headers, lists, code blocks, bold/italic text

Report template is fully customizable via `config/report_template.html`.

## Configuration

### dashboards.yaml

Add or remove dashboards by editing `config/dashboards.yaml`. No code changes needed.

#### Single URL per dashboard

```yaml
dashboards:
  - id: finance-report
    name: "Budget Forecast"
    url: "https://sharepoint.com/..."
```

#### Multiple URLs per dashboard group

```yaml
dashboards:
  - id: ops-metrics
    name: "Security Vulnerability Metrics"
    urls:
      - name: "Vulnerability Trends"
        url: "https://tableau.com/..."
      - name: "Age Breakdown"
        url: "https://tableau.com/..."
```

Both formats can be mixed freely. Each URL becomes its own browser tab.

### Supported Dashboard Types

| Type | Auth Method | Example |
|---|---|---|
| Tableau Cloud | Tableau email → Microsoft SSO | Tableau views and dashboards |
| SharePoint / Excel Online | Microsoft SSO (shared session) | Excel files opened in browser |
| JIRA / Confluence | Atlassian email → SSO or API token | JIRA dashboards, Confluence pages |
| AI Pro | Azure AD → Microsoft SSO | AI Pro dashboards |
| Power BI | Microsoft SSO | Power BI reports |
| Smartsheet | Email entry → Microsoft SSO | Smartsheet dashboards and reports |
| CloudHealth | Email submit → SSO redirect | CloudHealth cost dashboards |
| CloudZero | Email submit → SSO redirect | CloudZero cost dashboards |

## Authentication

### Login Strategies

Defined in `src/auth/` (split across modules — see `src/auth/README.md`):

| Function | Flow |
|---|---|
| `login_tableau` | Tableau email → Microsoft SSO (username + password) → "Stay signed in?" |
| `login_atlassian` | Atlassian email → SSO redirect (uses existing Microsoft session) or API token fallback; runs in its own isolated tab |
| `login_sso` | Direct Microsoft SSO (username + password) |
| `login_aipro` | AI Pro → Azure AD button → Microsoft SSO → dismiss welcome |
| `login_powerbi` | Power BI → Microsoft SSO |
| `login_smartsheet` | Smartsheet email entry → Microsoft SSO; skips if already logged in or already on Microsoft login page |
| `login_cloudhealth` | CloudHealth email submit → waits for full Broadcom SSO → Microsoft → CloudHealth redirect chain (up to 90 s) before closing tab |
| `login_cloudzero` | CloudZero email submit → waits for SSO redirect chain to complete |

All strategies check if login fields are visible before interacting. If the session is still valid, the step is skipped automatically.

### Session Persistence

The browser uses a persistent profile stored in `.auth_session/`. This means:

- **First run**: Guided setup mode — user logs in manually, `.setup_complete` marker saved
- **Subsequent runs**: Fully automated — login steps skipped if session is valid
- **Certificate selection**: macOS cert dialog appears on first run only; the choice is remembered

The orchestrator also prevents Chromium's "Restore pages" prompt by:
- Deleting session/crash marker files before each launch
- Writing `exit_type: "Normal"` and `restore_on_startup: 5` to `Default/Preferences`
- Passing `--disable-session-crashed-bubble` and `--hide-crash-restore-bubble` flags

To force a fresh login:

```bash
rm -rf .auth_session/
```

### Atlassian Authentication

Atlassian login is optional. If `ATLASSIAN_EMAIL` and `ATLASSIAN_API_TOKEN` are set in `.env`, the agent will authenticate to Atlassian Cloud before opening dashboard tabs.

The flow is:
1. Navigate to `id.atlassian.com/login`
2. Enter email and submit
3. Wait for redirect — corporate Atlassian typically redirects to SSO
4. If SSO handles it (via existing Microsoft session), login completes automatically
5. If a password field appears instead, the API token is used as the password

This allows JIRA dashboards and Confluence pages to load without an interactive login popup.

## Testing

Run the test suite from the repo root:

```bash
source .venv/bin/activate
cd dashboard-agent
pytest
```

Tests are in `tests/` and cover auth registry dispatch and login strategy logic. For async Playwright tests, use `pytest-asyncio`.

## Dependencies

| Package | Purpose |
|---|---|
| `playwright` | Browser automation (Chromium via CDP) |
| `python-dotenv` | Load credentials from `.env` |
| `pyyaml` | Parse `dashboards.yaml` |
| `Pillow` | Screenshot stitching and image processing |

## Design Decisions

| Decision | Rationale |
|---|---|
| Detached subprocess + CDP | Browser survives script exit; Playwright's context manager would kill it |
| First-run setup mode | First Microsoft SSO triggers device auth requiring a client cert; manual login handles this once |
| `.setup_complete` marker | Distinguishes first run (guided) from subsequent runs (automated) |
| Persistent browser profile | Avoids re-authentication and cert selection on every run |
| Crash marker cleanup + Preferences | Prevents Chromium's "Restore pages" bubble on every launch |
| `wait_for_load_state("load")` over `"networkidle"` | Tableau and SharePoint make continuous background requests; `networkidle` never resolves |
| `--start-maximized` + `no_viewport=True` | Ensures the browser fills the screen on macOS (CDP `windowState` doesn't work on macOS) |
| Tabs in one window | Single persistent context shares auth session across all tabs |
| Conditional login steps | Each step checks field visibility before interacting; skips when session is valid |
| Fire-and-forget | Script exits after opening all tabs; browser stays open for the manager |
| Atlassian SSO with token fallback | Corporate Atlassian uses SSO redirect; API token is the non-interactive fallback |
| Single `url` and `urls` list support | Flexible config — group related dashboards or list them individually |
| Isolated auth windows per service | CloudHealth and Atlassian each open their own tab; all lingering tabs (SSO popups, redirects) are closed before the next service starts so logins don't overwrite each other |
| `wait_for_url()` after CloudHealth submit | CloudHealth SSO chain goes via `access.broadcom.com` → Microsoft → back; awaited up to 90 s rather than a fixed sleep. Timeout failures are logged with the current URL instead of being swallowed silently. |
| `NODE_NO_WARNINGS=1` env var | Playwright spawns an internal Node.js server that emits DEP0169 warnings; setting this before the first `async_playwright()` call suppresses them cleanly |
