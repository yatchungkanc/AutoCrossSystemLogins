# Technical Specification

Project: AutoCrossSystemLogins, also known as Project HotGates
Date: 2026-06-04
Status: Draft based on current repository implementation

## 1. System Overview

AutoCrossSystemLogins is a Python 3.11 local CLI application built around Playwright. It launches a detached Chromium process with a persistent user data directory, connects to it over Chrome DevTools Protocol, performs authentication and tab management, then disconnects while leaving the browser available for the user.

The same browser session is reused by the graph report pipeline. URL inputs are opened or matched against existing tabs, reliable graph regions are captured as PNG images, the images are analyzed by the GitHub Copilot CLI, and a static HTML report is generated.

## 2. Repository Layout

```text
run.py
setup.sh
dashboard-agent/
  .env.example
  config/
    dashboards.yaml.example
    prompts.yaml
    report_template.html
  src/
    orchestrator.py
    graph_report.py
    graph_inputs.py
    screenshot_capture.py
    analysis.py
    report_generator.py
    config/loader.py
    auth/
      config.py
      common.py
      ms_sso_services.py
      email_sso_services.py
      registry.py
      strategies.py
  tests/
  output/
docs/
spec/
```

## 3. Runtime Dependencies

- Python >= 3.11.
- Playwright >= 1.40.
- Playwright-managed Chromium.
- python-dotenv >= 1.0.
- PyYAML >= 6.0.
- Pillow >= 10.0.
- GitHub Copilot CLI extension for graph analysis, exposed as `copilot`.

## 4. Entry Points

### 4.1 Root CLI

`run.py` is the primary user entry point.

- `python run.py`: open all configured dashboards.
- `python run.py --list`: print dashboard groups and tab counts.
- `python run.py <filter> [...]`: open matching dashboard groups.
- `python run.py graph-report ...`: run graph report generation.

`run.py` adds `dashboard-agent/` to `sys.path` so imports under `src.*` resolve from the repository root.

### 4.2 Installed Script

`dashboard-agent/pyproject.toml` declares a console script:

```text
dashboard-agent = "src.orchestrator:main"
```

The repository documentation currently emphasizes `python run.py` as the supported workflow.

## 5. Configuration

### 5.1 Credentials

`dashboard-agent/src/config/loader.py` loads `dashboard-agent/.env` and returns a `Credentials` dataclass.

Fields:

- `email`: sourced from `TABLEAU_EMAIL`.
- `username`: sourced from `SSO_USERNAME`.
- `password`: sourced from `SSO_PASSWORD`.
- `atlassian_email`: sourced from `ATLASSIAN_EMAIL`.
- `atlassian_token`: sourced from `ATLASSIAN_API_TOKEN`.
- `cloudhealth_email`: sourced from `CLOUDHEALTH_EMAIL`.
- `cloudzero_email`: sourced from `CLOUDZERO_EMAIL`.

The loader currently requires `TABLEAU_EMAIL`, `SSO_USERNAME`, and `SSO_PASSWORD` for normal orchestration.

### 5.2 Dashboard Registry

`dashboard-agent/config/dashboards.yaml` is the local dashboard registry and is gitignored. `dashboard-agent/config/dashboards.yaml.example` is the committed template.

Supported group shape:

```yaml
dashboards:
  - id: group-id
    name: "Group Display Name"
    auth_type: powerbi
    urls:
      - name: "Dashboard Tab Name"
        url: "https://example.invalid/report"
```

Groups may also use a single `url`.

`src.orchestrator.load_dashboards()` flattens groups into tab records:

```python
{"id": group_id, "name": tab_name, "url": url, "auth_type": auth_type}
```

Filters are case-insensitive substring matches against group `id` or group `name`.

### 5.3 Prompt and Template Configuration

- `dashboard-agent/config/prompts.yaml` defines the Copilot analysis prompt and focus instructions.
- `dashboard-agent/config/report_template.html` defines the HTML shell used by `report_generator.py`.

## 6. Browser Session Architecture

### 6.1 Persistent Profile

The persistent browser profile is stored under:

```text
dashboard-agent/.auth_session/
```

The first-run marker is:

```text
dashboard-agent/.auth_session/.setup_complete
```

### 6.2 Detached Chromium

`src.orchestrator.launch_detached_browser()` launches Chromium with:

- `--remote-debugging-port=9222`
- `--user-data-dir=dashboard-agent/.auth_session`
- `--start-maximized`
- crash restore suppression flags
- `start_new_session=True`

The process is detached so it survives Python process exit.

### 6.3 CDP Connection

Playwright connects with:

```text
http://localhost:9222
```

The code intentionally overrides `browser.close` before stopping Playwright so disconnecting does not close the user-visible Chromium process.

## 7. Dashboard Opening Workflow

### 7.1 First Run

`orchestrator.main()` calls `run_setup()` when `.setup_complete` is absent.

Setup flow:

1. Launch detached Chromium on port 9222.
2. Connect over CDP.
3. Navigate to Tableau SSO and ask the user to complete login manually.
4. If CloudZero is configured, ask the user to complete CloudZero login manually.
5. Navigate to Atlassian login and allow manual login or skip.
6. Touch `.setup_complete`.
7. Disconnect from Playwright and leave Chromium open.

### 7.2 Subsequent Runs

`orchestrator.run()` performs:

1. Load credentials.
2. Resolve dashboard tab records.
3. Launch detached Chromium.
4. Connect over CDP.
5. Determine required auth types from selected dashboards.
6. Execute page-based strategies in dependency order:
   - `email_only`
   - `sso`
   - `aipro`
   - `powerbi`
   - `smartsheet`
7. Execute context-based strategies:
   - `cloudhealth` when enabled in the registry
   - `cloudzero`
   - `atlassian`
8. Close extra auth pages.
9. Open dashboard tabs in parallel.
10. Mark each tab failed if it lands on a known login redirect domain.
11. Return `True` only when all requested tabs open successfully.

## 8. Authentication Design

Authentication is registry-driven through `dashboard-agent/src/auth/registry.py`.

`AuthStrategySpec` defines:

- strategy function
- whether the strategy receives a `Page` or `BrowserContext`
- required credential fields
- optional skip message for missing credentials

Current registry:

| auth_type | Function | Target | Credentials |
|---|---|---|---|
| `email_only` | `login_tableau` | Page | `email`, `username`, `password` |
| `sso` | `login_sso` | Page | `username`, `password` |
| `aipro` | `login_aipro` | Page | `username`, `password` |
| `powerbi` | `login_powerbi` | Page | `username`, `password` |
| `smartsheet` | `login_smartsheet` | Page | `email`, `username`, `password` |
| `cloudzero` | `login_cloudzero` | Context | `cloudzero_email` |
| `atlassian` | `login_atlassian` | Context | `atlassian_email`, `atlassian_token` |

CloudHealth code exists but is disabled in the active registry.

## 9. Graph Report Architecture

### 9.1 Source Resolution

`graph_report.resolve_graph_sources()` combines:

- explicit `--graph` values parsed by `graph_inputs.py`
- dashboard group URLs resolved from `dashboards.yaml`

Validation rules:

- At least one graph or group is required.
- Graph specs must use `Name=PATH_OR_URL`.
- Names must be non-empty and unique case-insensitively.
- Local paths must exist and be files.
- URL sources must use HTTP or HTTPS.

### 9.2 URL Capture

`screenshot_capture.capture_graphs_from_url()`:

1. Connects to Chromium over CDP.
2. Finds an existing tab for the requested URL when possible.
3. Opens a new tab otherwise.
4. Waits for load and partial network idle.
5. Waits for capture readiness.
6. Captures a full-page screenshot.
7. Crops reliable graph boxes into individual PNG files.
8. Returns graph crop paths and page metadata.

URL matching normalizes host, path, fragment path, and query items. It ignores volatile query keys such as `iid`, `session`, `authuser`, and `prompt`.

Capture logic is conservative. It avoids login redirects, loading states, and unrelated page chrome. It includes special support for CloudZero Explorer and CloudZero dashboard views, including the newer `next.cloudzero.com` layout.

### 9.3 Analysis

`analysis.py`:

1. Loads `prompts.yaml`.
2. Builds a prompt with report metadata, graph count, exact graph IDs, friendly names, and image paths.
3. Requires the `copilot` binary in `PATH`.
4. Invokes:

```text
copilot -p <prompt> --allow-all-tools
```

The process streams stdout until completion and drains stderr concurrently to avoid pipe deadlocks. Non-zero exit codes and empty output raise `AnalysisError`.

### 9.4 Report Generation

`report_generator.py`:

1. Strips Copilot activity preamble before the first markdown heading.
2. Copies graph images into a sibling asset directory named after the report file.
3. Builds an exact image map keyed by graph ID, friendly name, copied filename, and original filename.
4. Converts supported markdown structures into HTML.
5. Embeds graph thumbnails only for graph-analysis tables whose first column is `Graph` or `Graph ID`.
6. Leaves unmatched labels as text and logs a warning rather than guessing.
7. Applies severity badge transformations for configured severity markers.

## 10. Output and Generated Files

Generated reports are written to:

```text
dashboard-agent/output/graph_report_<timestamp>.html
```

Graph assets are copied to:

```text
dashboard-agent/output/graph_report_<timestamp>_graphs/
```

Temporary URL captures are created under:

```text
dashboard-agent/output/temp/
```

The graph report agent removes its temp capture directory after successful or failed runs.

## 11. Error Handling

- Missing `.env`: `FileNotFoundError` with copy instructions.
- Missing required env values: `EnvironmentError` naming missing keys.
- Unknown auth type: warning and false result.
- Dashboard tab redirects to login: tab marked failed.
- Invalid graph specs: argparse error.
- Missing CDP browser for URL capture: fatal browser connection error with required action.
- Unreliable URL capture: skipped when other graphs remain; fatal if no graphs remain.
- Missing Copilot CLI: fatal with install instruction.
- Report generation failure: fatal report-generation error.

## 12. Testing

The current test suite uses `unittest` and mocks for external browser and auth behavior.

Covered areas include:

- graph input parsing and validation
- URL graph source parsing
- prompt construction with graph IDs, graph names, image paths, and focus areas
- HTML report image embedding with friendly display names
- exact Graph ID mapping without filename guessing
- skipped URL sources when local or other valid sources remain
- all-failed URL sources raising `GraphInputError`
- auth registry dispatch for page and context strategies
- optional credential skips
- unknown auth type handling

Recommended command:

```bash
python -m unittest discover dashboard-agent/tests
```

## 13. Security Considerations

- `.env`, `dashboards.yaml`, `.auth_session`, temp files, and generated graph asset directories are gitignored.
- The system stores browser session state locally in the persistent Chromium profile.
- The tool should be run only on a trusted workstation.
- Logs should not print credential values.
- Adding new docs or examples should avoid copying private dashboard URLs from the local `dashboards.yaml`.

## 14. Known Technical Debt and Constraints

- CDP port `9222` is fixed, which may conflict with other local browser automation.
- First-run setup is manual by design because certificate and MFA flows are not reliably automatable.
- The credential loader requires core Tableau/SSO credentials even for workflows that may not need Tableau.
- The report markdown converter is purpose-built, not a full CommonMark implementation.
- URL capture support is necessarily vendor-layout sensitive.
- CloudHealth code remains present but disabled in the active auth registry.
- Tests do not currently exercise a real browser session, real SSO, real Copilot invocation, or rendered visual report validation.

