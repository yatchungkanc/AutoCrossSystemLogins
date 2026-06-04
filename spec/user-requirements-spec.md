# User Requirements Specification

Project: AutoCrossSystemLogins, also known as Project HotGates
Date: 2026-06-04
Status: Draft based on current repository implementation

## 1. Purpose

AutoCrossSystemLogins is a local command-line browser automation tool for opening multiple internal operational dashboards in one persistent Chromium session. It reduces daily manual login and navigation effort for managers and operators who need to monitor security, cost, finance, planning, and collaboration dashboards across several SaaS systems.

The project also includes a graph report generator that captures graph images from local files, dashboard URLs, or configured dashboard groups, analyzes those images with the GitHub Copilot CLI, and produces a portable HTML report with graph thumbnails and an executive summary.

## 2. Target Users

- Manager or service owner who needs a daily overview across many internal dashboards.
- FinOps, security, operations, or delivery stakeholder who needs recurring dashboard evidence and summaries.
- Developer or maintainer who adds dashboard groups, login strategies, tests, or capture improvements.

## 3. User Problems

- Users spend time manually opening many dashboard URLs every day.
- Each dashboard family may use a different authentication flow.
- Microsoft SSO, certificate prompts, MFA, and account pickers can interrupt automation.
- Users need a repeatable way to capture and summarize chart evidence from dashboards.
- Generated reports need to remain portable, with images correctly linked to the analysis rows.

## 4. In Scope

- Local CLI execution from the repository root through `python run.py`.
- First-run manual SSO setup that creates a persistent browser profile.
- Subsequent automated login and dashboard tab opening.
- Dashboard registry configuration through `dashboard-agent/config/dashboards.yaml`.
- Dashboard group listing and filtering by group ID or name fragment.
- Authentication support for the configured `auth_type` values:
  - `email_only`
  - `sso`
  - `aipro`
  - `powerbi`
  - `smartsheet`
  - `cloudzero`
  - `atlassian`
- Graph report generation from:
  - Named local graph image files.
  - Named dashboard URLs.
  - Dashboard groups from `dashboards.yaml`.
- URL capture by reusing an already-open Playwright/Chromium session over CDP.
- HTML report generation with copied relative graph assets.
- Deterministic graph IDs such as `G001`, `G002`, and exact graph-image mapping.

## 5. Out of Scope

- Hosted multi-user web application.
- Server-side credential storage or shared credential vault integration.
- Replacing dashboard vendor permissions or SSO policy.
- Real-time monitoring, alerting, or scheduled background execution.
- Guaranteed capture support for every arbitrary dashboard layout.
- Direct API ingestion from Tableau, Power BI, CloudZero, Atlassian, or Smartsheet.

## 6. Functional Requirements

### 6.1 Setup

- The system shall provide a bootstrap script, `./setup.sh`, that prepares the Python environment, installs dependencies, installs Playwright Chromium, and creates `dashboard-agent/.env` from the example if needed.
- The system shall require Python 3.11 or newer.
- The system shall support a pyenv-selected environment when `.python-version` is present and pyenv is available.
- The system shall keep user credentials outside committed source files.

### 6.2 Credential Configuration

- The user shall configure credentials in `dashboard-agent/.env`.
- The system shall require `TABLEAU_EMAIL`, `SSO_USERNAME`, and `SSO_PASSWORD` for the current credential loader.
- The system shall support optional service-specific credentials such as `ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN`, and `CLOUDZERO_EMAIL`.
- The system shall fail with a clear error when required environment values are missing.

### 6.3 Dashboard Configuration

- The user shall configure dashboard groups in `dashboard-agent/config/dashboards.yaml`.
- Each dashboard group shall define:
  - Unique `id`.
  - Display `name`.
  - `auth_type`.
  - Either a single `url` or a list of named `urls`.
- The system shall flatten configured dashboard groups into individual browser tabs.
- The system shall list available groups with `python run.py --list`.
- The system shall allow users to open a subset of groups by passing group ID or name fragments.

### 6.4 First-Run Authentication

- On first run, the system shall launch Chromium with a persistent browser profile.
- The system shall guide the user through manual login steps that cannot be safely automated, such as certificate selection or MFA.
- The system shall create `dashboard-agent/.auth_session/.setup_complete` after setup.
- The system shall reuse the persistent browser profile on later runs.
- The user shall be able to reset setup by removing `dashboard-agent/.auth_session/`.

### 6.5 Automated Dashboard Opening

- The system shall launch a maximized Chromium window as a detached process.
- The system shall connect to Chromium over Chrome DevTools Protocol.
- The system shall run only the authentication strategies required by the selected dashboard groups.
- The system shall open configured dashboard URLs as tabs.
- The system shall report per-tab success or failure.
- The system shall leave the browser window open after the script exits.

### 6.6 Graph Report Generation

- The user shall invoke report generation with `python run.py graph-report`.
- The user shall be able to pass repeated `--graph "Name=/path/or/url"` values.
- The user shall be able to pass dashboard groups positionally or through repeated `--group` flags.
- The user shall be able to provide optional `--focus` values.
- The user shall be able to provide a report title with `--title`.
- The system shall validate graph names, duplicate names, local file existence, and URL formats.
- The system shall capture URL-based graphs using the existing browser session when possible.
- The system shall skip URL sources that cannot produce reliable graph crops when other valid sources remain.
- The system shall fail clearly when no graph images are available for analysis.
- The system shall invoke the GitHub Copilot CLI for image analysis.
- The system shall generate a timestamped HTML report in `dashboard-agent/output/`.
- The system shall copy graph assets into a sibling `<report>_graphs/` directory.
- The system shall use deterministic graph IDs and exact mappings to avoid wrong thumbnail links.

### 6.7 Automatic Report Trigger

- When the normal dashboard launch includes both `ops-metrics` and `cloudzero-dashboard`, and all requested tabs open successfully, the system shall automatically generate the configured graph report for those groups.
- If any requested dashboard tab fails to open, the system shall skip the automatic graph report and print a clear message.

## 7. Non-Functional Requirements

- Reliability: The tool should skip already-valid sessions and avoid unnecessary login work.
- Recoverability: First-run setup and auth session state should be resettable by deleting `.auth_session`.
- Privacy: `.env`, `dashboards.yaml`, auth sessions, temp files, and generated graph asset folders should not be committed.
- Portability: Generated reports should use relative asset paths so the HTML and asset folder can be moved together.
- Maintainability: Authentication strategies should be registry-driven and easy to extend.
- Observability: CLI logging should show setup, auth, tab opening, capture, analysis, and report generation progress.
- Safety: URL capture should avoid analyzing login pages, loading skeletons, or non-graph header/filter areas.
- Testability: Parsing, report mapping, auth dispatch, and graceful failure behavior should remain covered by automated tests.

## 8. Acceptance Criteria

- A new user can run `./setup.sh`, configure `.env` and `dashboards.yaml`, complete first-run setup, and open configured dashboards with `python run.py`.
- `python run.py --list` displays configured dashboard groups and tab counts.
- `python run.py <group>` opens only matching dashboard groups.
- Missing required credentials produce a clear error.
- Unknown `auth_type` values are reported and treated as failed auth.
- `python run.py graph-report --graph "Name=/existing/image.png"` generates an HTML report and copies the image into a sibling asset folder.
- Duplicate graph names are rejected case-insensitively.
- URL graph sources require a running CDP browser session and fail with clear instructions when no browser is available.
- Graph table rows using `G001`, `G002`, and later IDs embed the exact corresponding graph image.
- Summary tables do not attempt to embed graph thumbnails.

## 9. Current Constraints and Assumptions

- The tool is designed for a trusted local machine.
- The fixed CDP port is `9222`.
- URL-based graph capture depends on an already-running Playwright-managed Chromium session.
- Copilot analysis requires the `copilot` binary in `PATH`, installed through the GitHub Copilot CLI extension.
- The configured dashboard registry may contain internal URLs and should remain uncommitted.
- The current credential loader requires Tableau and SSO credentials even if a user intends to run only graph-report with local image files.
- CloudZero capture support is specialized for known legacy and newer CloudZero layouts.
- The report markdown renderer is intentionally lightweight and supports the structures produced by the configured prompt.

