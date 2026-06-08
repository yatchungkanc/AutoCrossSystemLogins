# AutoCrossSystemLogins (Project HotGates)

Browser automation CLI that logs into multiple internal dashboards (Tableau, SharePoint, JIRA, Power BI, Smartsheet, CloudZero, Atlassian) in a single persistent Chromium session using SSO/token-based authentication.

## Quick Start

### 1. Install

```bash
./setup.sh
```

This uses the Python environment selected by `.python-version` when pyenv is available, falls back to `.venv` otherwise, installs all dependencies, downloads the Playwright-managed Chromium binary, and copies `.env.example` → `.env`.

### 2. Configure credentials

Edit `dashboard-agent/.env`:

```env
SSO_USERNAME=<username>@domain.net
SSO_PASSWORD=<password>
TABLEAU_EMAIL=<email>
ATLASSIAN_EMAIL=<email>
ATLASSIAN_API_TOKEN=<api_token>
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

  - id: cloudzero-dashboard
    name: "CloudZero"
    auth_type: cloudzero
    url: "https://app.cloudzero.com/analytics/dashboards/<dashboard-id>/view"

  # ... etc
```

Each entry requires:
- `id` — unique identifier (used internally)
- `name` — display name shown in logs
- `auth_type` — one of `email_only`, `sso`, `aipro`, `powerbi`, `smartsheet`, `cloudzero`, `atlassian`
- `url` (single) or `urls` (list of `name`/`url` pairs)

`dashboards.yaml` is gitignored — it is never committed. `dashboards.yaml.example` is the committed template.

### 4. First run (one-time manual setup)

```bash
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
python run.py                                      # Open all dashboards
python run.py --list                               # List available dashboard groups
python run.py <id-or-name> [<id-or-name> ...]      # Open matching dashboard groups only
python run.py graph-report --graph "Name=/path/to/graph.png"
python run.py graph-report --graph "Name=https://next.cloudzero.com/explorer?..."
python run.py graph-report ops-metrics cloudzero-dashboard
python run.py graph-report --group ops-metrics --group cloudzero-dashboard
python run.py graph-report --graph "Name=/path/to/graph.png" --focus "anomalies"
```

### Open all dashboards

Launches a maximized Chromium window, authenticates (or skips if session is still valid), and opens every configured dashboard as a tab. The script exits and the browser stays open.

Graph reports are generated only when you explicitly run `python run.py graph-report ...`.

### Open specific dashboards

Pass one or more group IDs or name fragments to open only matching dashboards:

```bash
python run.py atlassian                  # open the Atlassian group
python run.py ops-metrics finance        # open two groups by ID
```

Run `python run.py --list` to see all available group IDs and names.

### Graph report

Replaces the earlier CloudHealth-specific report flow. `graph-report` analyzes one or more local graph image files, CloudZero URLs, or dashboard groups from `dashboards.yaml` and generates a generic HTML report. Local image inputs go straight to analysis; CloudZero URL inputs reuse an already-open browser tab when possible, otherwise they open a new tab in the existing Playwright browser session and capture reliable chart images before analysis.

Requires the GitHub Copilot CLI to be installed:

```bash
gh extension install github/gh-copilot
```

The report workflow:
1. Validates one or more `--graph "Name=/path/to/image-or-url"` or dashboard group inputs
2. Captures individual graph images for CloudZero URL inputs using the screenshot utility
3. Assigns deterministic graph IDs (`G001`, `G002`, etc.) and invokes `copilot -p` to analyze the graph images
4. Generates a timestamped HTML report in `dashboard-agent/output/`
5. Copies graph images into a relative `<report>_graphs/` folder next to the report

#### Example

```bash
python run.py graph-report \
  --graph "AWS Account Vulnerability Trends=/tmp/trends.png" \
  --graph "CloudZero Product Spend=https://next.cloudzero.com/explorer?..." \
  --focus "anomalies, trend changes" \
  --title "Weekly Graph Review"
```

Dashboard groups can be supplied positionally or with repeated `--group` flags:

```bash
python run.py graph-report ops-metrics cloudzero-dashboard
python run.py graph-report --group ops-metrics --group cloudzero-dashboard
```

**Input**: Local graph/chart images or CloudZero URLs, named by the caller, plus dashboard groups from `dashboards.yaml`. URL capture requires a running browser session from `python run.py`.

**URL capture behavior**:
- URL capture is restricted to `app.cloudzero.com` and `next.cloudzero.com`. Other URL hosts are skipped with a warning and report generation continues with remaining valid inputs.
- Reuses an already-open tab when the normalized URL matches, including reordered or extra query parameters.
- For CloudZero Explorer URLs, captures the chart plus the related data table below it when present.
- For CloudZero dashboard `/view` URLs, captures each individual dashboard tile from the embedded dashboard frame using `div#styled-tile-dashboard`.
- For the newer CloudZero layout, prioritizes `main[data-scroll-container="main"]` and recognizes Chakra UI table panels marked with `data-testid="table-root"`.
- Skips a URL if no reliable chart or no-results tile can be captured; report generation continues with remaining valid inputs. If every requested URL is skipped, the command exits with a clear error.

**Output**: A timestamped HTML page (`graph_report_<timestamp>.html`) with structured graph analysis and an executive summary.

- **Graph Analysis** — per-graph findings linked by generated Graph IDs, with caller-provided graph names displayed in the report.
- **Executive Summary** — cross-graph patterns, largest movements, anomalies, data-quality notes, and recommended follow-up.

All graph thumbnails are clickable — clicking opens a full-size lightbox overlay. The report generator uses exact Graph ID/name mappings only; it does not guess images from similar filenames.

#### Sample generated report

The sample report at [docs/images/graph_report_20260505_175623.html](docs/images/graph_report_20260505_175623.html) shows the current graph-report format using 13 CloudZero captures stored beside it in [docs/images/graph_report_20260505_175623_graphs/](docs/images/graph_report_20260505_175623_graphs/).

![Sample graph-report HTML showing analyzed graphs and analysis results](docs/images/graph_report_20260505_175623_preview.png)

That report demonstrates the final output structure:
- **Graph Analysis** — one table row per captured image, with the graph thumbnail, scope/time range, key values, trend, and observations.
- **Executive Summary** — cross-graph findings such as overall spend patterns, largest movements, critical anomalies, data-quality notes, and recommended actions.
- **Relative graph assets** — each thumbnail is loaded from the sibling `graph_report_20260505_175623_graphs/` folder, so the HTML can be moved with its asset folder and still render correctly.

Example findings from the sample:
- The RDP product portfolio showed elevated spend in the last 10 days of the reviewed period, with portfolio-wide daily spend rising from about `$981` on `04/05` to about `$2,460` on `05/02`.
- `G011` identified the largest movement: `aws-rt-dataconfidential-nonprod` in `rdp-consumption`, up `273%` and about `$14,860.25` over 30 days, with a single-day peak of about `$3.03K` on `04/15`.
- The data-quality section confirmed all 13 images were readable and flagged one misleading duplicate label where a broader all-products view was captured.

## Prerequisites

- Python 3.11+
- Chromium — installed automatically by `setup.sh` via `playwright install chromium`
- GitHub Copilot CLI — required only for `python run.py graph-report`

## Project Layout

```
run.py                        # Entry point
setup.sh                      # One-time bootstrap
dashboard-agent/
  .env                        # Credentials (not committed)
  config/
    dashboards.yaml           # Dashboard registry (add/remove URLs here)
    prompts.yaml              # Generic graph analysis prompts
    report_template.html      # HTML report template
  src/
    orchestrator.py           # Browser launch, auth, tab management
    graph_report.py           # Generic graph report orchestrator
    auth/                     # Auth strategies per service
    config/loader.py          # Credential loader
  output/                     # Generated HTML reports
  tests/                      # pytest suite
  README.md                   # Full architecture and design details
```

See [dashboard-agent/README.md](dashboard-agent/README.md) for full architecture, auth strategy details, and configuration options.
