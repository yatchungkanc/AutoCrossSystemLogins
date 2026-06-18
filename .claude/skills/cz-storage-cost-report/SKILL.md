---
name: cz-storage-cost-report
description: >-
  Build a multi-month CloudZero cost breakdown for one or more tag values,
  structured Service → (tag) → Account on a monthly basis, and render it as a
  standalone HTML report with stacked-bar charts. Use when asked for "cost
  trends", "storage cost trends", "cost by service/account/product over N
  months", "break down S3 + Backup + RDS + EBS + EFS", or "generate an HTML cost
  report". Generic over tag dimension (Product, Team, Environment, CostCode),
  service set, region, and cost type — storage is just the default preset.
---

# CloudZero storage cost report (Service → Product → Account, monthly)

Produces a monthly cost-trend breakdown across **storage services** for a set of
tag values, then optionally renders it to HTML using the project report template.
This generalizes the workflow that produced `dashboard-agent/storage_cost_report.html`.

## When to use
- "Show me cost trends of storage services for Product=X, Y, Z over the past 6 months."
- "Break down by accounts and services / by service then account, monthly."
- "Generate an HTML report for this output."

## Key facts (Elsevier org, learned)
- **Org / dimension FQDIDs**
  - Product tag: `CZ:Tag:Product` (other useful: `CZ:Account`, `CZ:Service`, `CZ:UsageType`, `CZ:UsageFamily`).
  - Account → human name: group by `User:AWS_Account_Tag:aws_account_tag_account_name`
    alongside `CZ:Account` (account IDs come back as numbers otherwise).
- **What counts as a "storage service"** (all AWS, region `USE2`):
  - `AmazonS3` and `AWSBackup` — the dominant two (>95% of storage spend).
  - `AmazonRDS` — include (database storage + instances).
  - **EBS is NOT its own service** — it's billed under `AmazonEC2`. Isolate it by
    filtering `CZ:Service=["AmazonEC2"]` **and**
    `CZ:UsageFamily=["Storage","System Operation","Provisioned Throughput"]`.
  - `AmazonEFS` exists as a service but is **$0** for the rdp-* products — confirm, don't assume.
- **S3 composition**: roughly Requests ≈ Storage ≈ half each, so per-account S3 reflects
  API activity as much as stored bytes. Bucket usage types as
  Storage(`TimedStorage*`) / Requests / DataTransfer / Mgmt(`StorageAnalytics|Inventory|Monitor`) / Other.
- **AWSBackup surges** are almost entirely `USE2-WarmStorage-ByteHrs-S3` (retained warm
  backup volume) — a lifecycle/retention optimization target, not restores/operations.

> **Usage templates:** copy-paste invocation forms are in `USAGE.md` (next to this file).

## Inputs (all but `tag_values` have defaults)
- `tag_values` (required): list of tag values, e.g. `["rdp-consumption","rdp-sources","rdp-works","rdp-content","rdp-document"]`.
- `tag_dimension`: default `CZ:Tag:Product`. Swap for `CZ:Tag:Team`, `CZ:Tag:Environment`, `CZ:Tag:CostCode`, etc.
- `months`: lookback window, default 6. Build a clean range: `start = first day of (today − months)`,
  `end = today`. The current month is **partial** — mark it `<Mon>*` and never compare it to full months.
- `services`: the **service catalog** (see below). Default = the storage preset. To do "all services" or a
  custom set, replace this list; the rest of the procedure is unchanged.
- `region`: usage-type prefix, default `USE2` (us-east-2). Only matters when filtering/bucketing by
  `CZ:UsageType` (e.g. `USE2-EBS:VolumeUsage.gp3`) — generalize as `<REGION>-…` or drop the prefix to span regions.
- `cost_type`: default `real_cost`. Others: `amortized_cost`, `billed_cost`, `usage_amount`, etc.

## Service catalog (the configurable part)
Each entry = how to isolate one "service row". The **storage preset** is:

| Service label | How to filter |
|---|---|
| AmazonS3  | `CZ:Service=["AmazonS3"]` |
| AWSBackup | `CZ:Service=["AWSBackup"]` |
| AmazonRDS | `CZ:Service=["AmazonRDS"]` |
| EBS       | `CZ:Service=["AmazonEC2"]` **and** `CZ:UsageFamily=["Storage","System Operation","Provisioned Throughput"]` |
| AmazonEFS | `CZ:Service=["AmazonEFS"]` (confirm; often `$0`) |

To genericize: any entry is just `{label, filters}`. Compute is `CZ:Service=["AmazonEC2"]` **minus** the EBS
usage families; "all services" is a single `group_by:["CZ:Service", tag_dimension, "CZ:Account"]` with no service filter.
Discover valid service / usage-family names first with `get_dimension_values` or a `get_available_dimensions` probe.

## Procedure
1. **Scope / discover** (optional sanity check): one `get_cost_data` grouped by
   `["CZ:Service"]`, filtered to the tag values, to confirm which services carry spend.
2. **Map account names**: `get_cost_data` grouped by
   `["CZ:Account","User:AWS_Account_Tag:aws_account_tag_account_name"]`.
3. **Per-service monthly pull** — for each entry in the service catalog, run `get_cost_data`
   with `cost_type`, `granularity:"monthly"`, `group_by:[tag_dimension,"CZ:Account"]`, and
   `filters = {tag_dimension: tag_values, ...entry.filters}`. (Storage preset = S3, AWSBackup,
   RDS, EBS, EFS as in the catalog table.) Treat any service whose filter returns empty as `$0`.
4. **For deeper cuts** (usage-type level), add `CZ:UsageType` to `group_by` (max 3 dims +
   granularity). **Watch for oversized results**: a 3-dim S3 query can exceed the tool's
   token limit and be spilled to a file — then aggregate it with `jq` (bucket usage types,
   sum per product/account/month). Avoid `sleep` in Bash (pyenv profile is slow); run jq in
   background and Read the task output file.
5. **Assemble** tables: Service → Product → Account → monthly, with per-service totals and a
   grand all-service total. Round to whole USD; show `—` for none, `<1` for sub-dollar.
6. **HTML report** (when asked): fill `dashboard-agent/config/report_template.html`
   placeholders — `{{timestamp}}`, `{{report_name}}`, `{{graph_count}}` (repurpose as period/
   scope), `{{content}}`. Reuse the template's `.table-wrapper`, `.alert {critical|warning|info|positive}`
   classes; add helper classes `.num` (right-align), `.prod`, `.acct`, `.total`. Write to
   `dashboard-agent/<name>_report_<YYYY-MM-DD>.html` (the `<YYYY-MM-DD>` is the
   generation date — same value as `{{timestamp}}`) and `open` it. Dating the filename
   keeps successive runs side by side instead of overwriting, since the current-month
   figures keep growing between pulls.
7. **Charts** (part of the HTML): add two **stacked bar charts** via Chart.js
   (`<script src="https://cdn.jsdelivr.net/npm/chart.js@4">`), x-axis = months:
   - **By service** — one dataset per service (the per-service monthly totals).
   - **By tag value** — one dataset per `tag_value` (sum each across all services per month).
   Both stacks reconcile to the same grand total each month — use that as a built-in check.
   Keep it self-contained and resilient: `maintainAspectRatio:false` inside a fixed-height
   `.chart-box`, money tooltips/ticks (`$Nk`), and a `typeof Chart === 'undefined'` fallback
   that swaps in a "see tables below" message if the CDN is blocked (plus a `<noscript>`).
   Reference implementation: the two charts in `dashboard-agent/storage_cost_report.html`.

## Gotchas
- **June/current month keeps growing** — re-pulling later yields higher partial figures; always label it `*` and don't compare to full months.
- Account `210275200797` (`aws-rt-dataconfidential-nonprod`) is a *non-prod* account that
  outspends prod — flag, don't silently report.
- The mirrored `rdp-works` Backup pair (`831790613400` + `471112847390` = `dataplatform-backup`)
  is a cross-account backup copy, not double counting.

## Output artifacts
- Markdown tables in chat, and/or `dashboard-agent/<name>_report_<YYYY-MM-DD>.html`
  (self-contained, opens standalone; filename carries the generation date so reruns don't overwrite).
- Reference example: `dashboard-agent/storage_cost_report.html`.
