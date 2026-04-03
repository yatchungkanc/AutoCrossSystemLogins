# AutoCrossSystemLogins (Project HotGates)

Browser automation CLI that logs into multiple internal dashboards (Tableau, SharePoint, JIRA, Azure, CloudHealth) in a single persistent Chromium session using SSO/token-based authentication.

## Quick Start

### 1. Install

```bash
./setup.sh
```

This creates a `.venv`, installs all dependencies, downloads the Playwright-managed Chromium binary, and copies `.env.example` → `.env`.

### 2. Configure credentials

Edit `dashboard-agent/.env`:

```env
SSO_USERNAME=<username>@domain.net
SSO_PASSWORD=<password>
TABLEAU_EMAIL=<email>
ATLASSIAN_EMAIL=<email>
ATLASSIAN_API_TOKEN=<api_token>
CLOUDHEALTH_EMAIL=<email>       # optional
CLOUDZERO_EMAIL=<email>         # optional
```

Generate an Atlassian API token at https://id.atlassian.com/manage-profile/security/api-tokens.

### 3. Configure dashboards

```bash
cp dashboard-agent/config/dashboards.yaml.example dashboard-agent/config/dashboards.yaml
```

Edit `dashboard-agent/config/dashboards.yaml` and replace the `<placeholder>` values with your actual dashboard URLs:

```yaml
dashboards:
  - id: tableau-dashboard
    name: "My Dashboard Group"
    auth_type: email_only
    urls:
      - name: "View 1"
        url: "https://<tableau-region>.online.tableau.com/#/site/<site>/views/..."
      - name: "View 2"
        url: "https://<tableau-region>.online.tableau.com/#/site/<site>/views/..."

  - id: cloudhealth-dashboard
    name: "CloudHealth"
    auth_type: cloudhealth
    url: "https://apps.cloudhealthtech.com/dashboard/<dashboard-id>"

  # ... etc
```

Each entry requires:
- `id` — unique identifier (used internally)
- `name` — display name shown in logs
- `auth_type` — one of `email_only`, `atlassian`, `cloudhealth`, `powerbi`, `cloudzero`
- `url` (single) or `urls` (list of `name`/`url` pairs)

`dashboards.yaml` is gitignored — it is never committed. `dashboards.yaml.example` is the committed template.

### 4. First run (one-time manual setup)

```bash
source .venv/bin/activate
python run.py
```

The browser opens and prompts you to complete each SSO login manually once. Press ENTER in the terminal after each step. A `.setup_complete` marker is saved — all future runs are fully automated.

To redo first-run setup:

```bash
rm -rf dashboard-agent/.auth_session/
python run.py
```

## Usage

```bash
source .venv/bin/activate

python run.py                                      # Open all dashboards
python run.py cloudhealth                          # Generate CloudHealth cost report
python run.py cloudhealth "cost by service"        # Report with a focus area
```

### Open all dashboards

Launches a maximized Chromium window, authenticates (or skips if session is still valid), and opens every configured dashboard as a tab. The script exits and the browser stays open.

### CloudHealth report

Requires the orchestrator browser session to already be running (`python run.py`) and the GitHub Copilot CLI to be installed:

```bash
gh extension install github/gh-copilot
```

The report workflow:
1. Captures full-page screenshots of CloudHealth dashboards
2. Invokes `copilot -p` to analyze cost trends and anomalies
3. Generates a timestamped HTML report in `dashboard-agent/output/`
4. Opens the report in a new browser tab

## Prerequisites

- Python 3.11+
- Chromium — installed automatically by `setup.sh` via `playwright install chromium`
- GitHub Copilot CLI — required only for `python run.py cloudhealth`

## Project Layout

```
run.py                        # Entry point
setup.sh                      # One-time bootstrap
dashboard-agent/
  .env                        # Credentials (not committed)
  config/
    dashboards.yaml           # Dashboard registry (add/remove URLs here)
    prompts.yaml              # CloudHealth analysis prompts
    report_template.html      # HTML report template
  src/
    orchestrator.py           # Browser launch, auth, tab management
    cloudhealth_report.py     # CloudHealth report orchestrator
    auth/                     # Auth strategies per service
    config/loader.py          # Credential loader
  output/                     # Generated HTML reports
  tests/                      # pytest suite
  README.md                   # Full architecture and design details
```

See [dashboard-agent/README.md](dashboard-agent/README.md) for full architecture, auth strategy details, and configuration options.
