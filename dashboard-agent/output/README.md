# Dashboard Agent Output Directory

This directory contains generated reports and captured screenshots from the dashboard agent.

## Structure

```
output/
  cloudhealth_report_YYYYMMDD_HHMMSS.html  # Generated HTML reports
  latest_analysis.md                        # Latest Copilot analysis (temp file)
  screenshots/
    YYYYMMDD_HHMMSS/                       # Screenshot sets organized by capture time
      00_full_page.png                      # Full dashboard screenshot
      01_section.png                        # Individual sections
      ...
```

## Reports

HTML reports are generated with timestamps and include:
- Dashboard screenshots
- Cost analysis and trends
- Executive summary
- Recommendations

Open any `.html` file in your browser to view the report.

## Screenshots

Screenshots are automatically captured when running the CloudHealth report generator and organized by capture timestamp for easy reference in analysis.
