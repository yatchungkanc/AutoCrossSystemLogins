# Dashboard Agent Output Directory

This directory contains generated graph reports and graph image assets from the dashboard agent.

## Structure

```
output/
  graph_report_YYYYMMDD_HHMMSS.html        # Generated graph analysis reports
  graph_report_YYYYMMDD_HHMMSS_graphs/     # Graph images copied beside the report
    001_Graph_Name.png
    ...
  latest_analysis.md                       # Latest Copilot analysis (temp file)
  temp/                                    # Temporary URL captures, cleaned after reports
```

## Reports

HTML reports are generated with timestamps.

Graph reports include:
- Per-graph findings linked by generated Graph IDs and displayed with caller-provided graph names
- Clickable graph thumbnails copied into a sibling `_graphs/` folder
- Cross-graph executive summary, anomalies, data-quality notes, and recommended follow-up

Graph thumbnails are embedded through exact Graph ID/name mappings. The report generator does not guess images from similar filenames; unknown graph labels are shown as text and logged for review.

Open any `.html` file in your browser to view the report.

## Captures

Graph-report URL captures are stored under `output/temp/` while the report is being built, then copied into the final `<report>_graphs/` folder and cleaned up. CloudZero dashboard `/view` URLs can produce multiple tile captures; CloudZero Explorer URLs can capture the chart plus its related data table, including newer Chakra UI table panels marked with `data-testid="table-root"`.
