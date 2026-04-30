#!/usr/bin/env python3
"""Root-level entry point for the dashboard agent.

Usage:
    python run.py                                     # Launch dashboards, then auto-report selected groups
    python run.py --list                              # List available dashboard groups
    python run.py <id-or-name> [<id-or-name> ...]     # Launch matching dashboards only
    python run.py graph-report --graph "Name=/path/to/graph.png"
    python run.py graph-report --graph "Name=https://dashboard.example/report"
    python run.py graph-report ops-metrics cloudzero-dashboard
    python run.py graph-report --group ops-metrics --group cloudzero-dashboard
    python run.py graph-report --graph "Name=/path/to/graph.png" --focus "anomalies"

Dashboard filter tokens are matched case-insensitively against the dashboard
group `id` and `name` fields defined in config/dashboards.yaml.
When ops-metrics and cloudzero-dashboard are included in a successful launch,
an automatic graph-report run analyzes those two groups.
"""
import asyncio
import sys
from pathlib import Path

# Ensure dashboard-agent/ is on the path so `src.*` imports resolve correctly
sys.path.insert(0, str(Path(__file__).resolve().parent / "dashboard-agent"))

AUTO_GRAPH_REPORT_GROUPS = ("ops-metrics", "cloudzero-dashboard")
AUTO_GRAPH_REPORT_TITLE = "Ops Metrics and CloudZero Graph Analysis Report"


def _group_ids(dashboards: list[dict]) -> set[str]:
    return {dashboard["id"] for dashboard in dashboards if dashboard.get("id")}


def _auto_report_targets_were_launched(filters: list[str] | None) -> bool:
    from src.orchestrator import load_dashboards

    launched_dashboards = load_dashboards(filters)
    return set(AUTO_GRAPH_REPORT_GROUPS).issubset(_group_ids(launched_dashboards))


def _build_auto_graph_report_args() -> list[str]:
    args = ["--title", AUTO_GRAPH_REPORT_TITLE]
    for group in AUTO_GRAPH_REPORT_GROUPS:
        args.extend(["--group", group])
    return args


if __name__ == "__main__":
    args = sys.argv[1:]

    if args and args[0] == "graph-report":
        from src.graph_report import main as graph_report_main
        asyncio.run(graph_report_main(args[1:]))
    elif args and args[0] == "--list":
        from src.orchestrator import list_dashboard_groups
        list_dashboard_groups()
    else:
        from src.orchestrator import main

        filters = args if args else None
        all_tabs_opened = main(filters)
        if all_tabs_opened and _auto_report_targets_were_launched(filters):
            from src.graph_report import main as graph_report_main

            asyncio.run(graph_report_main(_build_auto_graph_report_args()))
        elif not all_tabs_opened:
            print("Skipping automatic graph report because not all dashboard tabs opened.")
