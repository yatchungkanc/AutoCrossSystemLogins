---
name: cz-tag-cost-projection
description: Project the current-month cloud cost for any CloudZero tag value and break the projection down by account (with account names) and service to surface cost drivers, optionally rendering the result as a standalone HTML report. Use when asked things like "projected cost of <tag>=<value> this month", "what is driving spend for tag X", "break down <tag> cost by account/service", or "generate an HTML projection report". Works for any tag dimension (Product, Team, Environment, CostCode, etc.), not just Product.
---

# CloudZero Tag Cost Projection

Projects the full-month cost for a single tag value from month-to-date actuals, then attributes the projection across accounts (named) and services to expose the drivers.

## When to use
- "What is the projected cost of `<tag>` = `<value>` for `<month>`?"
- "Break down the projection by account and service."
- Any tag dimension works: `Product`, `Team`, `Environment`, `CostCode`, `SubProduct`, etc.

> **Usage templates:** copy-paste invocation forms are in `USAGE.md` (next to this file).

## Inputs to resolve first
1. **Tag name** (e.g. `Product`, `Team`) and **tag value** (e.g. `rdp-works`).
2. **Target month**. Default to the current month. Today's date determines how much of the month is actual vs. projected.
3. **Cost type**. Default `real_cost` (actual incurred). Offer `amortized_cost` when the user cares about RI/Savings-Plan-adjusted economics — note that amortized typically projects materially higher than real_cost.
4. **Output mode**. Default = Markdown tables in chat. When the user asks for "an HTML report" / "a report" / "generate HTML", also render the standalone HTML report (see "HTML report" below).

## Procedure

### Step 1 — Find the tag dimension FQDID
Tag values can live under several similarly-named dimensions. Discover the right one:
```
get_available_dimensions(filter="<tag>")
```
Candidates are usually `CZ:Tag:<Tag>` plus variants (`Default.<Tag>`, uppercase, custom `User:Defined:*`). Do **not** assume — confirm in Step 2.

### Step 2 — Confirm the value exists under that dimension
Run `get_dimension_values` against the likely candidate(s), scoped to the target month, using `match` to filter:
```
get_dimension_values(dimension="CZ:Tag:<Tag>", match="<partial value>",
                     date_range={start: <month start>, end: <month end>})
```
Pick the dimension whose returned list contains the exact value. If multiple match, prefer the one with non-empty results for the target month.

### Step 3 — Establish the projection basis (complete days only)
Pull daily costs for the value across the month to date:
```
get_cost_data(date_range={start:<month-1st>, end:<month-end exclusive>},
              filters={"CZ:Tag:<Tag>": ["<value>"]},
              granularity="daily", cost_type="<type>")
```
- **Exclude the most recent 1–2 days** if they are abnormally low — that is billing lag, not a real drop.
- Let `N` = number of complete days, `MTD` = sum over those days.
- `daily_rate = MTD / N`; `days_in_month` per the calendar; **projection = daily_rate × days_in_month**.
- Inspect the trend: if recent days are clearly rising/falling, also compute a **recent-7-day run rate** and present a range (full-month-avg → recent-rate). State which end is more likely and why.

### Step 4 — Break down by account
Query the same window/filter grouped by account (no time granularity = totals):
```
get_cost_data(date_range=<complete-day window: month-1st → first incomplete day>,
              filters={"CZ:Tag:<Tag>": ["<value>"]},
              group_by=["CZ:Account"], cost_type="<type>")
```
Project each account's MTD by the same `days_in_month / N` factor.

### Step 5 — Resolve account names
Account rows come back as bare IDs. Map them to names by grouping on the account-name dimension:
```
get_cost_data(..., group_by=["CZ:Account", "User:Defined:accounttag_AccountName"], ...)
```
`User:Defined:accounttag_AccountName` ("Elsevier Account Name") is the preferred map for this org. If empty, fall back to `User:AWS_Account_Tag:aws_account_tag_account_name`.

### Step 6 — Break down by service (drivers)
```
get_cost_data(..., group_by=["CZ:Account", "CZ:Service"], cost_type="<type>", limit=100)
```
Aggregate by service across accounts to find the top cost categories, and note the top account×service cells. `group_by` allows up to 3 dimensions, so account+service in one call is fine.

## Output format
- **Headline:** MTD actual ($, N complete days), daily rate, and **projected full-month** figure (or range).
- **Projection by account** table — columns in this exact order:
  `Product | Account name | Account ID | MTD | Projected | Share`
  One row per (product, account). When multiple tag values are requested, list every product's account rows (grouped/sorted by product, then by projected spend descending). Share is the account's % of that product's total.
- **Projection by service** table — columns in this exact order:
  `Product | Service | Account name | Account ID | MTD | Projected | Share`
  One row per (product, service, account). When multiple tag values are requested, list every product's rows (grouped/sorted by product, then by projected spend descending). Share is the row's % of that product's total. Obtain this from the `group_by=["CZ:Tag:<Tag>", "CZ:Account", "CZ:Service"]` query and join account names from the account-name map.
- **Cost drivers:** 3–5 bullets calling out the concentrated account×service blocks and anything notable (lumpy/fixed charges, large nonprod spend, backup/retention costs).

## HTML report (when asked)
When the user wants an HTML report, render the same content into the project template
`dashboard-agent/config/report_template.html` and write a standalone file.

1. **Read the template** and substitute its placeholders (string replace, leave the rest as-is):
   - `{{timestamp}}` → generation time (e.g. `2026-06-17 14:30 UTC`).
   - `{{report_name}}` → e.g. `Cost projection — Product=rdp-works (Jun 2026, real_cost)`.
   - `{{graph_count}}` → **repurpose** as the scope line, e.g. `MTD 15/30 days · real_cost`.
   - `{{content}}` → the report body HTML (below). The `<h1>` reads "Graph Analysis Report" and
     the footer says "dashboard-agent" — that's expected from the shared template; leave them.
2. **Body `{{content}}`** mirrors the Markdown output, reusing the template's existing CSS:
   - **Headline** as an `<div class="alert info">`: MTD actual ($, N complete days), daily rate,
     and projected full-month figure (or range). Use `alert warning` if you flagged billing-lag/
     trend caveats, `alert positive` for a clean projection.
   - **Projection by account** — a `<div class="table-wrapper"><table>…</table></div>` with the
     exact columns `Product | Account name | Account ID | MTD | Projected | Share`.
   - **Projection by service** — another `.table-wrapper` table with columns
     `Product | Service | Account name | Account ID | MTD | Projected | Share`.
   - **Cost drivers** — a `<ul>` of the 3–5 driver bullets.
   - Right-align money/share cells (add an inline `style="text-align:right"` or a small
     `.num { text-align:right }` rule injected in `{{content}}`); render `—` for none and `<1`
     for sub-dollar. Sort rows by product, then projected spend descending.
3. **Write** the filled HTML to `dashboard-agent/<tag>_<value>_projection_report.html`
   (slugify the value), then `open` it. The file is self-contained — no charts are required
   for a projection, so the template's Chart.js/lightbox scripts can stay unused.

## Gotchas
- **Most recent day is usually incomplete** — always check and exclude it from the run-rate basis.
- **`date_range.end` is exclusive.** For "complete days Jun 1–15" use `end: 2026-06-16T00:00:00Z`.
- **Lumpy charges** (AWSBackup, MWAA environment fees) have low `projected_row_count` but often still accrue ~1 record/day, so they scale linearly — verify before assuming a charge is one-off.
- **real_cost vs amortized_cost** diverge significantly; always state which one the numbers represent.
- **Response cap is 5 MB / row caps apply** — if a query is too large, tighten the date range or add filters.
- Confirm the active org with `get_user_organizations` if results look unexpectedly empty.
