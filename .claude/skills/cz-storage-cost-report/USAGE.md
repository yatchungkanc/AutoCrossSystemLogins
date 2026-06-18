# cz-storage-cost-report — usage templates

Copy-paste templates for invoking the skill. The only required field is `tag_values`;
every other field has a sensible default you can delete if you don't need to override it.
The skill reads these as intent, not strict syntax — plain English works too.

## Quick form (one-liner)

```
/cz-storage-cost-report tag_values=[rdp-consumption, rdp-sources, rdp-works, rdp-content, rdp-document] months=6 html=yes
```

## Full spec block (paste + edit; drop any line to use its default)

```
/cz-storage-cost-report

# WHAT TO BREAK DOWN
tag_dimension : CZ:Tag:Product          # or CZ:Tag:Team | CZ:Tag:Environment | CZ:Tag:CostCode
tag_values    : [rdp-consumption, rdp-sources, rdp-works, rdp-content, rdp-document]

# TIME
months        : 6                        # lookback window; current month shown partial (e.g. Jun*)

# SERVICES (default = storage preset: S3, AWSBackup, RDS, EBS, EFS)
services      : storage                  # storage | all | [AmazonS3, AmazonRDS, ...]

# COST BASIS
cost_type     : real_cost                # real_cost | amortized_cost | billed_cost | usage_amount
region        : USE2                      # usage-type prefix; only matters for usage-type cuts

# OUTPUT
structure     : Service > Product > Account (monthly)
html          : yes                       # yes = render dashboard-agent/<name>_report_<YYYY-MM-DD>.html with charts
charts        : by-service, by-tag        # stacked bar charts in the HTML
```

## Common variations

**By team, 12 months, amortized, HTML report:**
```
/cz-storage-cost-report tag_dimension=CZ:Tag:Team tag_values=[platform, ingestion, search] months=12 cost_type=amortized_cost html=yes
```

**All services (not just storage), tables only:**
```
/cz-storage-cost-report tag_values=[rdp-works] services=all months=6 html=no
```

**Custom service set + usage-type detail:**
```
/cz-storage-cost-report tag_values=[rdp-consumption] services=[AmazonS3, AWSBackup] months=6 detail=usage_type html=yes
```

**Plain English (also fine):**
```
storage cost trends for rdp-works and rdp-sources over the last 9 months, by team, HTML with charts
```

## Notes
- `html=yes` writes `dashboard-agent/<name>_report_<YYYY-MM-DD>.html` (filename carries the
  generation date so reruns don't overwrite) and opens it; the report includes two stacked-bar
  charts whose by-service and by-tag stacks reconcile to the same monthly totals.
- The current (in-progress) month is always partial — it is marked `*` and should not be
  compared one-to-one with full months.
- See `SKILL.md` for the full procedure, service catalog, and gotchas.
