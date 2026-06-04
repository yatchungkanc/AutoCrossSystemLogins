# Roadmap

Project: AutoCrossSystemLogins, also known as Project HotGates
Date: 2026-06-04
Status: Draft based on current repository implementation

## 1. Product Direction

AutoCrossSystemLogins should remain a practical local operator tool: fast to run, easy to configure, and reliable enough for daily dashboard review. Near-term work should reduce setup friction and make graph reports more dependable. Medium-term work should improve maintainability, observability, and scheduled usage. Long-term work can explore richer integrations only after the local CLI foundation is stable.

## 2. Current Baseline

Already implemented:

- Local setup script for Python environment, package install, Chromium install, and `.env` creation.
- Persistent Chromium session with first-run manual setup.
- Registry-driven authentication strategies for Tableau/email, Microsoft SSO, AI Pro, Power BI, Smartsheet, CloudZero, and Atlassian.
- Dashboard registry through `dashboard-agent/config/dashboards.yaml`.
- Dashboard group listing and filtered launch.
- Detached browser launch over CDP port `9222`.
- Graph report CLI for local images, URLs, and dashboard groups.
- URL capture with existing-tab reuse and CloudZero-specific graph capture support.
- GitHub Copilot CLI analysis.
- Static HTML report generation with copied relative graph assets.
- Deterministic graph IDs and exact thumbnail linking.
- Automated graph report trigger when `ops-metrics` and `cloudzero-dashboard` both launch successfully.
- Unit tests for parsing, auth dispatch, prompt construction, skip behavior, and report image mapping.

## 3. Guiding Principles

- Keep the primary workflow local and simple.
- Prefer configuration over code changes for adding dashboard groups.
- Keep credential and dashboard URL secrets out of committed files.
- Fail clearly when dependencies or sessions are missing.
- Favor exact mappings and explicit state over fuzzy matching.
- Add tests around risky behavior before broad refactors.

## 4. Phase 1: Stabilize the Daily CLI

Goal: Make the current dashboard-opening workflow easier to trust and easier to recover.

Priority items:

- Add a `doctor` or `check` command that validates Python version, `.env`, required credentials, `dashboards.yaml`, Playwright Chromium, CDP port availability, and Copilot availability.
- Make credential requirements conditional on selected dashboard groups instead of always requiring Tableau and SSO values.
- Detect an already-running Chromium instance on port `9222` before launching a new detached process.
- Add clearer remediation messages for port conflicts, stale browser state, and missing `dashboards.yaml`.
- Add schema validation for `dashboards.yaml`, including duplicate group IDs, missing names, missing URLs, and unknown `auth_type` values.
- Add a command to reset or re-run first-run setup without requiring users to remember the `.auth_session` path.

Suggested acceptance criteria:

- `python run.py doctor` reports pass/fail status for all local prerequisites.
- A user can run a graph report from local images without unrelated Tableau credentials.
- Invalid dashboard config fails before launching the browser.
- Port conflicts are explained with a specific recovery action.

## 5. Phase 2: Harden Graph Capture and Reporting

Goal: Improve reliability and explainability of generated graph reports.

Priority items:

- Add capture diagnostics that save a small JSON manifest for each URL source, including final URL, matched existing tab, capture boxes, skipped reason, and image paths.
- Keep optional failed-capture artifacts for debugging when a flag such as `--debug-capture` is provided.
- Add report metadata for skipped sources so the final HTML can show what was not analyzed.
- Add a `--no-auto-report` flag for normal dashboard launches.
- Add a dry-run mode that resolves dashboard groups and graph sources without opening tabs or invoking Copilot.
- Add stronger output validation for Copilot markdown, including required graph IDs and required sections.
- Add tests for URL normalization, skipped-source reporting, and malformed Copilot output.

Suggested acceptance criteria:

- A graph report includes a visible data-quality section when any requested source is skipped.
- Debug capture mode gives maintainers enough context to improve selectors without rerunning the whole workflow blindly.
- Malformed analysis output cannot silently produce a misleading graph-to-thumbnail mapping.

## 6. Phase 3: Improve Auth Extensibility and Maintainability

Goal: Make new services and changed login flows easier to support.

Priority items:

- Document the process for adding a new `auth_type`.
- Add typed config validation for `AuthStrategySpec`.
- Split provider selectors and URLs into provider config where practical.
- Add service-level auth health checks that can verify an active session without opening all dashboards.
- Review and either re-enable, remove, or fully archive the disabled CloudHealth path.
- Add integration-style tests around mocked Playwright pages for common login states such as already logged in, account picker, email prompt, and password prompt.

Suggested acceptance criteria:

- Adding a new auth strategy requires one strategy function, one registry entry, and tests.
- Session validation can identify which service needs re-authentication.
- Disabled or legacy provider code has an explicit documented status.

## 7. Phase 4: Operational Quality

Goal: Make the tool more comfortable for repeated team use without turning it into a large platform.

Priority items:

- Add structured logs or a machine-readable run summary.
- Add stable report naming options, such as `--output` or `--slug`.
- Add report retention guidance or cleanup command for old generated outputs.
- Add optional scheduling documentation for macOS launchd, cron, or CI-like local runners.
- Add a release checklist that includes tests, sample report generation, and documentation review.
- Add screenshots or short usage examples for common workflows.

Suggested acceptance criteria:

- Each run can produce a concise summary file with opened tabs, failed tabs, report path, and skipped graph sources.
- Users can select output paths without manually moving generated files.
- Maintainers have a repeatable release and verification checklist.

## 8. Phase 5: Longer-Term Options

Goal: Consider larger improvements only after the local CLI is stable.

Possible directions:

- Replace Copilot CLI dependency with a configurable analysis provider abstraction.
- Add direct export integrations for vendors that provide stable chart or report APIs.
- Add optional scheduled report generation with local notification.
- Add a lightweight local UI for selecting dashboard groups and opening generated reports.
- Add encrypted local credential storage or integration with a workstation keychain.
- Add multi-profile support for users who need separate tenants or roles.

These options should be evaluated against the core value of the project: quick local access to dashboards with minimal operational burden.

## 9. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Dashboard vendor DOM changes break capture | Reports skip graphs or capture wrong regions | Keep conservative capture rules, add debug manifests, expand tests with saved fixtures |
| SSO changes break login automation | Dashboard launch fails | Keep first-run/manual fallback, improve auth health checks, document reset flow |
| Fixed CDP port conflicts | Browser connection fails or attaches to wrong process | Add port checks and optional configurable port |
| Copilot CLI unavailable or output format changes | Report generation fails or malformed reports appear | Add preflight checks and output validation |
| Internal URLs or credentials leak into commits | Security incident | Keep gitignore coverage, avoid copying local registry values into docs, add secret scanning guidance |
| Report analysis overstates uncertain image data | Bad business decisions | Preserve prompt rules for unreadable data, expose capture limitations, include skipped-source metadata |

## 10. Suggested Next Milestone

The next milestone should be a stability milestone:

Name: `v0.2 Local Reliability`

Scope:

- `doctor` command.
- Conditional credential validation.
- Dashboard YAML schema validation.
- Browser/CDP port conflict handling.
- Graph report skipped-source visibility.
- Tests for the above behavior.

Definition of done:

- Existing unit tests pass.
- New validation behavior is covered by tests.
- README usage examples are updated.
- A maintainer can diagnose the three most common failures without reading source code: missing config, auth/session issue, and graph capture issue.

