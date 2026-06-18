# cz-tag-cost-projection — usage templates

Copy-paste templates for invoking the skill. The only required fields are `tag_name` and
`tag_value`; every other field has a sensible default you can delete if you don't need to
override it. The skill reads these as intent, not strict syntax — plain English works too.

## Quick form (one-liner)

```
/cz-tag-cost-projection tag_name=Product tag_value=rdp-works month=current cost_type=real_cost
```

## Full spec block (paste + edit; drop any line to use its default)

```
/cz-tag-cost-projection

# WHAT TO PROJECT
tag_name   : Product                       # or Team | Environment | CostCode | SubProduct
tag_value  : rdp-works                      # one value, or a list: [rdp-works, rdp-consumption, ...]

# TIME
month      : current                        # current | 2026-06 ; today determines actual-vs-projected split

# COST BASIS
cost_type  : real_cost                      # real_cost | amortized_cost (amortized projects materially higher)

# OUTPUT
html       : no                             # no = markdown tables in chat (default); yes = render + open HTML
# html=yes -> renders dashboard-agent/<tag>_<value>_projection_<YYYY-MM-DD>.html and opens it
```

## Common variations

**Single product, current month, default tables in chat:**
```
/cz-tag-cost-projection
Project this month's cost for Product=rdp-works, broken down by account and service.
```

**Multiple values (portfolio), full month, with HTML report:**
```
/cz-tag-cost-projection tag_name=Product tag_value=[rdp-works, rdp-consumption, rdp-sources, rdp-content, rdp-document] month=2026-06 cost_type=real_cost html=yes
```

**By team, amortized economics:**
```
/cz-tag-cost-projection tag_name=Team tag_value=platform month=current cost_type=amortized_cost
```

**Drivers focus (what's pushing spend):**
```
/cz-tag-cost-projection tag_name=Product tag_value=rdp-consumption
What is driving the projected spend? Break down by account and service and call out the top drivers.
```

**Plain English (also fine):**
```
projected June cost of Product=rdp-works this month, by account and service, as an HTML report with the date in the filename
```

## What you get back
- **Headline:** MTD actual ($, N complete days), daily rate, and projected full-month figure —
  or a range (full-month average → recent-7-day run rate) when spend is clearly trending.
- **Projection by account** table: `Product | Account name | Account ID | MTD | Projected | Share`.
- **Projection by service** table: `Product | Service | Account name | Account ID | MTD | Projected | Share`.
- **Top cost drivers:** 3–5 bullets on the concentrated account×service blocks and anything notable.

## Notes
- The projection extrapolates from **complete days only** — the most recent 1–2 days are dropped
  as billing lag, and a rising/falling trend is surfaced as a range, not a single number.
- `cost_type=amortized_cost` typically projects **materially higher** than `real_cost`; the report
  always states which basis the numbers represent.
- `html=yes` fills `dashboard-agent/config/report_template.html` and writes
  `dashboard-agent/<tag>_<value>_projection_<YYYY-MM-DD>.html` (slugified value), then opens it.
- See `SKILL.md` for the full procedure, the HTML-report step, and gotchas.
