---
description: "Navigate to the CloudHealth dashboard, screenshot each graph, and interpret the results"
argument-hint: "Optional: specific graph name or metric to focus on (e.g. 'cost by service', 'trend'). Leave blank for full report."
agent: "agent"
tools: ["mcp_microsoft_pla_browser_navigate", "mcp_microsoft_pla_browser_take_screenshot", "mcp_microsoft_pla_browser_snapshot", "mcp_microsoft_pla_browser_wait_for", "mcp_microsoft_pla_browser_scroll", "view_image", "read_file"]
---

Read the CloudHealth dashboard and interpret all visible graphs. Focus area: **$ARGUMENTS** (if blank, report on everything).

**Interpretation Guidelines:**
- Focus on **data-driven observations** with specific values and ranges
- For cost-by-account graphs: analyze **6-month trend direction** (upward/downward/sideways)
- For cost-by-service graphs: identify **top 5 resources** and **spikes >20%**
- Support all findings with **concrete values** (e.g., "$35K → $45K, +29%")
- Do NOT describe graph types (bar chart, line chart, etc.) — focus on the data

## Step 1 — Get the CloudHealth URL

Read [dashboards.yaml](../../dashboard-agent/config/dashboards.yaml) and extract the `url` for the entry with `auth_type: cloudhealth`.

## Step 2 — Navigate to the dashboard

Navigate the browser to the CloudHealth dashboard URL found above.  
Wait for the page to finish loading — use `wait_for` with selector `[class*="chart"], [class*="graph"], [class*="widget"], canvas` or a 5-second pause if no chart selector is found.

> **Note**: The orchestrator must already be running and the browser must be open with an active CloudHealth session. If you land on a login page, stop and tell the user to run `python -m src.orchestrator` first.

## Step 3 — Full-page screenshot

Take a full-page screenshot of the dashboard. Use `view_image` to display it and note:
- Page title and dashboard name
- Overall layout: how many sections/panels are visible
- Any dates, time ranges, or filters shown at the top

## Step 4 — Locate and screenshot each graph

Use `snapshot` to get the accessibility tree of the page and identify distinct chart/graph/widget regions.

For each distinct graph or data panel found:
1. Scroll to bring it fully into view
2. Take a focused screenshot covering just that panel
3. Use `view_image` to examine it

## Step 5 — Interpret each graph

For each graph or data panel, provide a data-driven interpretation. **Do not describe graph types** (bar chart, line chart, etc.).

### For "Cost by Accounts" graphs:
```
### <Graph Title>
- **Time range**: The period shown (e.g. Mar 2025 - Mar 2026)
- **6-month trend**: Over the most recent 6 months, is spending **upward**, **downward**, or **sideways**?
  - Provide starting and ending values with percentage change
  - Example: "Upward trend: $35K (Sep 2025) → $45K (Feb 2026), +29% increase"
- **Peak and low values**: Highest and lowest monthly costs with dates
- **Account breakdown**: Which accounts contribute most to total spend (with %)
- **Notable patterns**: Any sudden changes, anomalies, or concerning trends
```

### For "Cost by Service Items" graphs:
```
### <Graph Title>
- **Time range**: The period shown
- **Top 5 resources by spend**: List the 5 highest-cost services with their typical monthly/weekly costs
  - Example: "1. RDS-GP3 Storage: $8-10K/month"
- **Cost spikes >20%**: Identify any services with spending increases exceeding 20% period-over-period
  - Provide baseline → peak values with percentage
  - Example: "S3-API: $200/month (Oct) → $400/month (Nov), +100% spike"
- **Cost trends**: Are top services growing, stable, or declining?
- **Notable patterns**: Any services with unusual volatility or recent changes
```

### For other graph types (weekly/daily trends, storage-specific, etc.):
```
### <Graph Title>
- **Time range**: The period shown
- **Value range**: Min to max values observed
- **Trend direction**: Increasing, decreasing, stable, or volatile
- **Anomalies**: Any values >20% above/below typical range with specific dates and values
- **Notable patterns**: Seasonality, weekend effects, or sudden changes
```

## Step 6 — Executive Summary & Recommendations

After analyzing all graphs, provide a comprehensive executive summary:

### Structure:
1. **Overall cloud spend status**: Current monthly run rate across all environments
2. **Top 5 cost drivers**: Services or accounts with highest spend (with values)
3. **Critical alerts & anomalies**: Issues requiring immediate attention (with severity: 🔴 Critical, ⚠️ Warning, ✅ Positive)
4. **6-month trend analysis**: Which environments are trending up/down/stable
5. **Recommended priority actions**: 
   - Immediate (this week)
   - Short-term (next 30 days)  
   - Medium-term (next quarter)
6. **Budget forecast**: 
   - Current quarterly spend
   - Annual run rate projection
   - Potential savings with optimizations
   - Specific optimization opportunities with estimated savings

### Guidelines:
- Use **specific values and ranges** throughout (e.g., "$20-25K/month", "60% YoY growth")
- Quantify all trends and changes with percentages
- Prioritize findings by financial impact
- Provide actionable recommendations with estimated savings
- Use clear severity indicators (🔴⚠️✅)

If $ARGUMENTS specified a focus area, lead the summary with findings specific to that topic.
