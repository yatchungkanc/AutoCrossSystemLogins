#!/usr/bin/env python3
"""Root-level entry point for the dashboard agent.

Usage:
    python run.py                                     # Launch browser with all dashboards
    python run.py --list                              # List available dashboard groups
    python run.py <id-or-name> [<id-or-name> ...]     # Launch matching dashboards only
    python run.py cloudhealth-report                  # Generate CloudHealth report
    python run.py cloudhealth-report "cost by service, anomaly detection"

Dashboard filter tokens are matched case-insensitively against the dashboard
group `id` and `name` fields defined in config/dashboards.yaml.
"""
import asyncio
import sys
from pathlib import Path

# Ensure dashboard-agent/ is on the path so `src.*` imports resolve correctly
sys.path.insert(0, str(Path(__file__).resolve().parent / "dashboard-agent"))

if __name__ == "__main__":
    args = sys.argv[1:]

    # CloudHealth functionality has been disabled
    # if args and args[0] == "cloudhealth-report":
    #     from src.cloudhealth_report import main as cloudhealth_main
    #     focus_area = args[1] if len(args) > 1 else ""
    #     asyncio.run(cloudhealth_main(focus_area))
    if args and args[0] == "--list":
        from src.orchestrator import list_dashboard_groups
        list_dashboard_groups()
    else:
        from src.orchestrator import main
        filters = args if args else None
        main(filters)
